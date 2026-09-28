package io.jenkins.plugins.queueoptimizer.scoring;

import io.jenkins.plugins.queueoptimizer.model.PriorityLevel;
import java.util.List;
import java.util.OptionalLong;

/**
 * The four queued jobs of report Appendix C, as data.
 *
 * <p>One fixture, two consumers: {@link AppendixCExampleTest} asserts the scores, and
 * {@code scripts/report/appendix_c.py} prints the table into the report from this same data
 * (task T8.3). That is the point. In Milestone 2 the published formula and the implemented
 * formula were different, and nothing connected the document to the code, so the divergence
 * survived to submission. Generating the table from the fixture the test asserts makes that
 * particular failure impossible rather than merely unlikely.
 *
 * <p>From the report: estimates in minutes, estMin 2.0 and estMax 8.0 across the queue, the
 * largest group has 2 members, and no aging has accumulated.
 */
public final class AppendixCFixture {

    /** Minutes, as the report states them, converted to the milliseconds the plugin works in. */
    private static final long MINUTE = 60_000L;

    /** The group holding build-api and the integration tests that consume its artifact. */
    public static final String GROUP_G1 = "G1";

    private AppendixCFixture() {}

    /**
     * The four jobs, in the report's table order.
     *
     * <p>Item ids ascend in submission order, which the report gives as build-frontend, build-api,
     * integration-tests-api, deploy-payment-service. That ordering is what makes the example
     * meaningful: under FIFO the HIGH deployment waits behind an eight-minute MEDIUM build.
     */
    public static List<ScoreInput> queue() {
        return List.of(
                // Independent HIGH deployment, submitted last under FIFO.
                new ScoreInput(
                        4L,
                        "deploy-payment-service",
                        PriorityLevel.HIGH,
                        "solo-deploy",
                        1,
                        0,
                        OptionalLong.of(3 * MINUTE),
                        0L,
                        4L),
                // LOW, but the producer of group G1, so it inherits the group's best score.
                new ScoreInput(
                        2L,
                        "build-api",
                        PriorityLevel.LOW,
                        GROUP_G1,
                        2,
                        0,
                        OptionalLong.of(2 * MINUTE),
                        0L,
                        2L),
                // MEDIUM consumer in G1; ordered after build-api by Kahn's algorithm.
                new ScoreInput(
                        3L,
                        "integration-tests-api",
                        PriorityLevel.MEDIUM,
                        GROUP_G1,
                        2,
                        1,
                        OptionalLong.of(7 * MINUTE),
                        0L,
                        3L),
                // The longest job in the queue, so T is exactly 0.
                new ScoreInput(
                        1L,
                        "build-frontend",
                        PriorityLevel.MEDIUM,
                        "solo-frontend",
                        1,
                        0,
                        OptionalLong.of(8 * MINUTE),
                        0L,
                        1L));
    }

    /** The order the report says the heap dispatches in. */
    public static List<String> expectedDispatchOrder() {
        return List.of(
                "deploy-payment-service", "build-api", "integration-tests-api", "build-frontend");
    }
}
