package io.jenkins.plugins.queueoptimizer.metrics;

import static java.nio.charset.StandardCharsets.UTF_8;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import com.sun.net.httpserver.HttpServer;
import hudson.util.Secret;
import io.jenkins.plugins.queueoptimizer.config.OptimizerConfiguration;
import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.function.BooleanSupplier;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.jvnet.hudson.test.JenkinsRule;
import org.jvnet.hudson.test.junit.jupiter.WithJenkins;

/**
 * The metrics publisher against a real HTTP endpoint (BUILD_PROMPT 4.3.9).
 *
 * <p>Its one hard rule is that it never blocks queue maintenance: Jenkins calls the recorders on
 * the thread that schedules builds. Coverage showed the publisher's paths almost untested (5% of
 * branches, 2026-10-20), the rule included, because no other test configures a backend. These
 * tests give it one: a local HTTP server that records what arrives and can answer slowly, wrongly
 * or not at all.
 */
@WithJenkins
class MetricsPublisherIT {

    /** A stand-in backend on a free loopback port. */
    private static final class Backend implements AutoCloseable {

        private final HttpServer server;
        private final ExecutorService threads = Executors.newCachedThreadPool();
        private final List<String> bodies = new CopyOnWriteArrayList<>();
        private final List<String> authorizations = new CopyOnWriteArrayList<>();
        private final CountDownLatch released = new CountDownLatch(1);
        private volatile int status = 202;
        private volatile boolean stalled;

        Backend() throws IOException {
            server = HttpServer.create(new InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0);
            server.createContext("/api/metrics", exchange -> {
                authorizations.add(String.valueOf(exchange.getRequestHeaders().getFirst("Authorization")));
                bodies.add(new String(exchange.getRequestBody().readAllBytes(), UTF_8));
                if (stalled) {
                    try {
                        released.await(20, TimeUnit.SECONDS);
                    } catch (InterruptedException interrupted) {
                        Thread.currentThread().interrupt();
                    }
                }
                exchange.sendResponseHeaders(status, -1);
                exchange.close();
            });
            server.setExecutor(threads);
            server.start();
        }

        String url() {
            return "http://127.0.0.1:" + server.getAddress().getPort() + "/api/metrics";
        }

        int received() {
            return bodies.size();
        }

        @Override
        public void close() {
            released.countDown();
            server.stop(0);
            threads.shutdownNow();
        }
    }

    private static void publishTo(String url) {
        OptimizerConfiguration config = OptimizerConfiguration.get();
        config.setMetricsEnabled(true);
        config.setMetricsBackendUrl(url);
        config.setMetricsToken(Secret.fromString("metrics-secret"));
    }

    private static void waitFor(BooleanSupplier condition, String what) throws InterruptedException {
        long deadline = System.currentTimeMillis() + 30_000;
        while (System.currentTimeMillis() < deadline) {
            if (condition.getAsBoolean()) {
                return;
            }
            Thread.sleep(20);
        }
        fail("timed out waiting until " + what);
    }

    @Test
    @DisplayName("an event reaches the backend as JSON, with the bearer token")
    void eventsReachTheBackendWithTheToken(JenkinsRule j) throws Exception {
        try (Backend backend = new Backend()) {
            publishTo(backend.url());
            MetricsPublisher publisher = MetricsPublisher.get();

            publisher.record(MetricEvent.of(MetricEvent.Kind.QUEUE_ENTERED).with("itemId", 7));

            waitFor(() -> publisher.getPublishedCount() == 1, "the event is published");
            assertEquals("Bearer metrics-secret", backend.authorizations.get(0));
            assertTrue(backend.bodies.get(0).contains("\"kind\":\"QUEUE_ENTERED\""), backend.bodies.get(0));
            assertTrue(backend.bodies.get(0).contains("\"itemId\":7"), backend.bodies.get(0));
        }
    }

    @Test
    @DisplayName("a backend that answers with an error is a counted failure, never an exception")
    void anErrorAnswerIsCounted(JenkinsRule j) throws Exception {
        try (Backend backend = new Backend()) {
            backend.status = 500;
            publishTo(backend.url());
            MetricsPublisher publisher = MetricsPublisher.get();

            publisher.record(MetricEvent.of(MetricEvent.Kind.BUILD_STARTED));

            waitFor(() -> publisher.getFailedCount() == 1, "the failure is counted");
            assertEquals(0, publisher.getPublishedCount());
        }
    }

    @Test
    @DisplayName("a backend that is not there is a counted failure too")
    void anUnreachableBackendIsCounted(JenkinsRule j) throws Exception {
        int closedPort;
        try (ServerSocket socket = new ServerSocket(0, 0, InetAddress.getLoopbackAddress())) {
            closedPort = socket.getLocalPort();
        }
        publishTo("http://127.0.0.1:" + closedPort + "/api/metrics");
        MetricsPublisher publisher = MetricsPublisher.get();

        publisher.record(MetricEvent.of(MetricEvent.Kind.BUILD_COMPLETED));

        waitFor(() -> publisher.getFailedCount() == 1, "the failure is counted");
    }

    @Test
    @DisplayName("a stalled backend never blocks recording: 1000 events wait, the rest are dropped and counted")
    void aStalledBackendNeverBlocksTheQueue(JenkinsRule j) throws Exception {
        try (Backend backend = new Backend()) {
            backend.stalled = true;
            publishTo(backend.url());
            MetricsPublisher publisher = MetricsPublisher.get();
            publisher.record(MetricEvent.of(MetricEvent.Kind.QUEUE_ENTERED));
            // The worker has taken that event and is now stuck inside its request.
            waitFor(() -> backend.received() == 1, "the worker is inside a request");

            long started = System.nanoTime();
            for (int i = 0; i < 1500; i++) {
                publisher.record(MetricEvent.of(MetricEvent.Kind.QUEUE_ENTERED).with("n", i));
            }
            long tookMillis = (System.nanoTime() - started) / 1_000_000;

            assertEquals(1000, publisher.getPendingCount(), "the queue holds its capacity and no more");
            assertEquals(500, publisher.getDroppedCount(), "everything beyond it is dropped and counted");
            assertTrue(
                    tookMillis < 2000,
                    "recording 1500 events took " + tookMillis + " ms; it must never wait for the backend");
        }
    }

    @Test
    @DisplayName("with no backend set, nothing is queued, and the recent events still serve the API")
    void withoutABackendOnlyTheRecentEventsAreKept(JenkinsRule j) {
        MetricsPublisher publisher = MetricsPublisher.get();

        publisher.record(MetricEvent.of(MetricEvent.Kind.BUILD_COMPLETED).with("job", "x"));

        assertEquals(0, publisher.getPendingCount());
        List<MetricEvent> recent = publisher.getRecent(10);
        assertEquals("x", recent.get(recent.size() - 1).getFields().get("job"));
    }

    @Test
    @DisplayName("the recent events keep the newest 500")
    void theRecentEventsAreBounded(JenkinsRule j) {
        MetricsPublisher publisher = MetricsPublisher.get();
        for (int i = 0; i < 600; i++) {
            publisher.record(MetricEvent.of(MetricEvent.Kind.QUEUE_LEFT).with("n", i));
        }

        List<MetricEvent> recent = publisher.getRecent(1000);

        assertEquals(500, recent.size());
        assertEquals(100, recent.get(0).getFields().get("n"));
        assertEquals(599, recent.get(499).getFields().get("n"));
    }
}
