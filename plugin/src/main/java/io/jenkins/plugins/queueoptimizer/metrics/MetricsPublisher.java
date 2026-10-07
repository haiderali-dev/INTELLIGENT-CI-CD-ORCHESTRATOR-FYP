package io.jenkins.plugins.queueoptimizer.metrics;

import edu.umd.cs.findbugs.annotations.NonNull;
import hudson.Extension;
import hudson.util.Secret;
import io.jenkins.plugins.queueoptimizer.config.OptimizerConfiguration;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * Posts metric events to the backend from a single background thread.
 *
 * <p>The design constraint that shapes everything here: this must never block queue maintenance.
 * Jenkins calls the queue listeners on the thread that is scheduling builds, so a slow or
 * unreachable backend must cost that thread nothing at all. Events therefore go into a bounded
 * queue and a daemon thread drains it.
 *
 * <p>When the queue is full, events are dropped and counted rather than buffered without limit.
 * An unbounded buffer in front of an unreachable endpoint is a memory leak that takes a controller
 * down, and losing metrics is strictly better than losing Jenkins. The drop count is reported on
 * the health endpoint so the loss is visible rather than silent.
 *
 * <p>Also keeps the last {@value #RECENT_RETAINED} events in memory for
 * {@code GET /dynamic-queue/metrics/recent}, which is how the experiment harness reads timings
 * without needing the backend at all.
 */
@Extension
public class MetricsPublisher {

    private static final Logger LOGGER = Logger.getLogger(MetricsPublisher.class.getName());

    /** Capacity from BUILD_PROMPT 4.3.9. Beyond this, events are dropped and counted. */
    private static final int CAPACITY = 1000;

    /** How many recent events to keep for the API. */
    private static final int RECENT_RETAINED = 500;

    private static final Duration HTTP_TIMEOUT = Duration.ofSeconds(10);

    private final BlockingQueue<MetricEvent> pending = new ArrayBlockingQueue<>(CAPACITY);
    private final Deque<MetricEvent> recent = new ArrayDeque<>();
    private final AtomicLong dropped = new AtomicLong();
    private final AtomicLong published = new AtomicLong();
    private final AtomicLong failed = new AtomicLong();

    private volatile Thread worker;

    /** @return the singleton, or null when Jenkins is not running */
    public static MetricsPublisher get() {
        return hudson.ExtensionList.lookupSingleton(MetricsPublisher.class);
    }

    /**
     * Records an event. Returns immediately, always.
     *
     * <p>Called from queue and run listeners, so it must not allocate much, must not block and
     * must not throw.
     */
    public void record(@NonNull MetricEvent event) {
        synchronized (recent) {
            recent.addLast(event);
            while (recent.size() > RECENT_RETAINED) {
                recent.removeFirst();
            }
        }

        OptimizerConfiguration config = OptimizerConfiguration.get();
        if (!config.isMetricsPublishable()) {
            // Nowhere to send it. The in-memory ring still serves the API.
            return;
        }
        if (!pending.offer(event)) {
            long total = dropped.incrementAndGet();
            if (total == 1 || total % 100 == 0) {
                LOGGER.warning(() -> "metrics queue full; dropped " + total
                        + " event(s). The backend at " + config.getMetricsBackendUrl()
                        + " is not keeping up or is unreachable.");
            }
            return;
        }
        ensureWorkerRunning();
    }

    /** The most recent events, newest last. */
    @NonNull
    public List<MetricEvent> getRecent(int limit) {
        synchronized (recent) {
            int size = recent.size();
            int take = Math.max(0, Math.min(limit, size));
            List<MetricEvent> events = new ArrayList<>(recent);
            return List.copyOf(events.subList(size - take, size));
        }
    }

    public long getDroppedCount() {
        return dropped.get();
    }

    public long getPublishedCount() {
        return published.get();
    }

    public long getFailedCount() {
        return failed.get();
    }

    public int getPendingCount() {
        return pending.size();
    }

    private void ensureWorkerRunning() {
        if (worker != null && worker.isAlive()) {
            return;
        }
        synchronized (this) {
            if (worker != null && worker.isAlive()) {
                return;
            }
            Thread thread = new Thread(this::drainForever, "dynamic-queue-metrics-publisher");
            // A daemon thread so it can never hold up a controller shutdown.
            thread.setDaemon(true);
            worker = thread;
            thread.start();
        }
    }

    /**
     * The HTTP client used to publish events.
     *
     * <p>Pinned to HTTP/1.1. {@link HttpClient#newBuilder()} defaults to HTTP/2, and for a cleartext
     * {@code http://} URL Java negotiates that through an HTTP/1.1 {@code Upgrade: h2c} request.
     * The backend is served by uvicorn, which does not implement that upgrade: it logs
     * "Unsupported upgrade request", then misparses the request, and every event came back 422. The
     * metrics pipeline therefore published nothing at all, which went unnoticed while no backend
     * existed to post to.
     *
     * <p>Package-private so a test can assert the version rather than trusting this comment.
     */
    static HttpClient newHttpClient() {
        return HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(HTTP_TIMEOUT)
                .build();
    }

    private void drainForever() {
        HttpClient client = newHttpClient();
        while (!Thread.currentThread().isInterrupted()) {
            try {
                MetricEvent event = pending.poll(30, TimeUnit.SECONDS);
                if (event == null) {
                    // Idle. Let the thread exit; record() restarts it on the next event.
                    return;
                }
                post(client, event);
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                return;
            } catch (RuntimeException unexpected) {
                LOGGER.log(Level.WARNING, unexpected, () -> "metrics publisher loop error");
            }
        }
    }

    private void post(HttpClient client, MetricEvent event) {
        OptimizerConfiguration config = OptimizerConfiguration.get();
        String url = config.getMetricsBackendUrl();
        if (url.isEmpty()) {
            return;
        }

        try {
            HttpRequest.Builder request = HttpRequest.newBuilder()
                    .uri(URI.create(url))
                    .timeout(HTTP_TIMEOUT)
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(event.toJson()));

            Secret token = config.getMetricsToken();
            if (token != null && !token.getPlainText().isEmpty()) {
                request.header("Authorization", "Bearer " + token.getPlainText());
            }

            HttpResponse<Void> response = client.send(request.build(), HttpResponse.BodyHandlers.discarding());
            if (response.statusCode() / 100 == 2) {
                published.incrementAndGet();
            } else {
                long count = failed.incrementAndGet();
                if (count == 1 || count % 100 == 0) {
                    LOGGER.warning(() ->
                            "metrics backend returned " + response.statusCode() + " (" + count + " failure(s) so far)");
                }
            }
        } catch (IOException | IllegalArgumentException problem) {
            long count = failed.incrementAndGet();
            if (count == 1 || count % 100 == 0) {
                LOGGER.log(Level.FINE, problem, () -> "metrics post failed (" + count + " so far)");
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
    }
}
