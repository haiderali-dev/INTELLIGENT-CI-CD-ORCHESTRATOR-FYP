package io.jenkins.plugins.queueoptimizer.sorter;

import static org.junit.jupiter.api.Assertions.assertTrue;

import hudson.model.Queue;
import hudson.model.queue.QueueSorter;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.logging.Handler;
import java.util.logging.Level;
import java.util.logging.LogRecord;
import java.util.logging.Logger;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.jvnet.hudson.test.JenkinsRule;
import org.jvnet.hudson.test.TestExtension;
import org.jvnet.hudson.test.junit.jupiter.WithJenkins;

/**
 * BUILD_PROMPT 4.3.7: Jenkins consults only the first registered {@code QueueSorter}, so the plugin
 * warns at startup when another is installed. Otherwise the optimizer can be switched on, report
 * itself enabled, and order nothing. Coverage showed the warning had never run in a test
 * (2026-10-20).
 */
@WithJenkins
class SorterConflictIT {

    /** A sorter from some other plugin, installed for one test only. */
    @TestExtension("anotherSorterIsNamedInAWarning")
    public static class CompetingSorter extends QueueSorter {
        @Override
        public void sortBuildableItems(List<Queue.BuildableItem> items) {
            // Orders nothing; it only has to exist.
        }
    }

    private static List<LogRecord> warningsDuring(Runnable action) {
        List<LogRecord> records = new CopyOnWriteArrayList<>();
        Logger logger = Logger.getLogger(DynamicQueueSorter.class.getName());
        Handler handler = new Handler() {
            @Override
            public void publish(LogRecord logRecord) {
                if (logRecord.getLevel() == Level.WARNING) {
                    records.add(logRecord);
                }
            }

            @Override
            public void flush() {}

            @Override
            public void close() {}
        };
        logger.addHandler(handler);
        try {
            action.run();
        } finally {
            logger.removeHandler(handler);
        }
        return records;
    }

    @Test
    @DisplayName("a second installed QueueSorter is named in a warning")
    void anotherSorterIsNamedInAWarning(JenkinsRule j) {
        List<LogRecord> warnings = warningsDuring(DynamicQueueSorter.SorterConflictWarning::warnAboutCompetingSorters);

        assertTrue(
                warnings.stream().anyMatch(r -> r.getMessage().contains(CompetingSorter.class.getName())),
                "the warning must name the competing sorter: " + warnings);
    }

    @Test
    @DisplayName("with this plugin's sorter alone, there is nothing to warn about")
    void aloneThereIsNoWarning(JenkinsRule j) {
        List<LogRecord> warnings = warningsDuring(DynamicQueueSorter.SorterConflictWarning::warnAboutCompetingSorters);

        assertTrue(warnings.isEmpty(), "no other sorter is installed: " + warnings);
    }
}
