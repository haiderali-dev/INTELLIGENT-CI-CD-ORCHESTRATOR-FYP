package io.jenkins.plugins.queueoptimizer.metrics;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.net.http.HttpClient;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Regression test for the metrics publisher's HTTP version.
 *
 * <p>This is not one of the tests BUILD_PROMPT 4.3.10 requires by name. It exists because the bug
 * it guards disabled the entire metrics data path without any symptom visible from the plugin side:
 * {@code HttpClient.newBuilder()} defaults to HTTP/2, and for a cleartext {@code http://} URL Java
 * negotiates that with an HTTP/1.1 {@code Upgrade: h2c} request. The backend is served by uvicorn,
 * which does not implement that upgrade, so it logged "Unsupported upgrade request", misparsed the
 * request, and returned 422 for every single event.
 *
 * <p>The plugin's own counters reported this only as {@code failedMetricCount}, and nothing was
 * watching that number, so an experiment would have completed with no queue timings recorded at
 * all. One assertion is cheap insurance against losing the data the report is built on.
 */
class MetricsPublisherHttpVersionTest {

    @Test
    @DisplayName("the publisher's client is pinned to HTTP/1.1, not Java's HTTP/2 default")
    void clientIsPinnedToHttp11() {
        HttpClient client = MetricsPublisher.newHttpClient();

        assertEquals(
                HttpClient.Version.HTTP_1_1,
                client.version(),
                "HTTP/2 over cleartext makes Java send Upgrade: h2c, which uvicorn rejects; "
                        + "every metric event then fails with 422");
    }

    @Test
    @DisplayName("Java's default really is HTTP/2, so the pin above is load-bearing")
    void javasDefaultWouldBeHttp2() {
        // Without this, a future reader could reasonably delete the .version() call believing it
        // restates a default. It does not.
        assertEquals(HttpClient.Version.HTTP_2, HttpClient.newBuilder().build().version());
    }
}
