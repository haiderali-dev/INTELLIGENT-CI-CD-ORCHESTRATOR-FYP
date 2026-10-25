package io.jenkins.plugins.queueoptimizer.scoring;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Writes the scored Appendix C fixture to {@code target/appendix-c.json} for
 * {@code scripts/report/appendix_c.py} (task T8.3).
 *
 * <p>The report's table is printed from what the plugin's own calculator computes on the fixture
 * {@link AppendixCExampleTest} asserts, so the document cannot drift from the code. Milestone 2's
 * report and code disagreed for months because nothing connected them. A Python copy of the
 * formula would only move that risk, so no such copy exists.
 *
 * <p>Every number is written to six decimals; the script rounds for print. Plain string building
 * keeps this package free of Jenkins imports, as its main code is.
 */
class AppendixCExportTest {

    static final Path OUTPUT = Path.of("target", "appendix-c.json");

    @Test
    @DisplayName("the scored Appendix C fixture is written for scripts/report/appendix_c.py")
    void writeTheScoredFixture() throws IOException {
        List<ScoredJob> scored = PriorityScoreCalculator.withReportDefaults().scoreAll(AppendixCFixture.queue());
        List<String> order = scored.stream()
                .sorted(PriorityScoreCalculator.compareForDispatch())
                .map(ScoredJob::jobName)
                .toList();

        List<String> rows = new ArrayList<>();
        for (ScoredJob job : scored) {
            rows.add(String.format(
                    Locale.ROOT,
                    "    {\"job\": \"%s\", \"level\": \"%s\", \"estimate_minutes\": %s, \"group\": \"%s\","
                            + " \"group_size\": %d, \"rank_in_group\": %d, \"U\": %.6f, \"D\": %.6f,"
                            + " \"T\": %.6f, \"base\": %.6f, \"aging\": %.6f, \"own\": %.6f,"
                            + " \"effective\": %.6f, \"inherited\": %b, \"dispatch_position\": %d}",
                    job.jobName(),
                    job.level(),
                    job.estimateMillis().isPresent()
                            ? String.format(
                                    Locale.ROOT, "%.3f", job.estimateMillis().getAsLong() / 60_000.0)
                            : "null",
                    job.groupId(),
                    job.groupSize(),
                    job.topologicalRank(),
                    job.urgencyFactor(),
                    job.dependencyFactor(),
                    job.executionTimeFactor(),
                    job.baseScore(),
                    job.agingBonus(),
                    job.ownScore(),
                    job.score(),
                    job.inheritedGroupScore(),
                    order.indexOf(job.jobName()) + 1));
        }
        String json =
                "{\n  \"fixture\": \"AppendixCFixture\",\n  \"calculator\": \"PriorityScoreCalculator.withReportDefaults()\",\n"
                        + "  \"rows\": [\n"
                        + String.join(",\n", rows)
                        + "\n  ]\n}\n";

        Files.createDirectories(OUTPUT.getParent());
        Files.writeString(OUTPUT, json, StandardCharsets.UTF_8);

        assertEquals(json, Files.readString(OUTPUT, StandardCharsets.UTF_8));
        assertEquals(AppendixCFixture.expectedDispatchOrder(), order);
    }
}
