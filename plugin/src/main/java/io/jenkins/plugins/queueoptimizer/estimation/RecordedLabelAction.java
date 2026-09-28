package io.jenkins.plugins.queueoptimizer.estimation;

import edu.umd.cs.findbugs.annotations.NonNull;
import hudson.Extension;
import hudson.model.InvisibleAction;
import hudson.model.Node;
import hudson.model.Run;
import hudson.model.TaskListener;
import hudson.model.listeners.RunListener;
import jenkins.model.Jenkins;

/**
 * Records, at build time, which agent label a build actually ran on.
 *
 * <p>The estimator's third similarity feature compares agent labels, and that comparison has to
 * be against where the build really ran, not where a job is configured to run today. An agent can
 * be relabelled or removed between a build finishing and the estimate that uses it, and a job's
 * label expression can be edited at any time. Reading it afterwards would silently compare the
 * wrong thing.
 */
public class RecordedLabelAction extends InvisibleAction {

    private final String label;

    public RecordedLabelAction(String label) {
        this.label = label == null ? "" : label;
    }

    /** @return the label recorded when the build started, never null */
    @NonNull
    public String getLabel() {
        return label == null ? "" : label;
    }

    /** Attaches the label to each run as it starts. */
    @Extension
    public static class Recorder extends RunListener<Run<?, ?>> {

        @Override
        public void onStarted(Run<?, ?> run, TaskListener listener) {
            if (run.getAction(RecordedLabelAction.class) != null) {
                return;
            }
            run.addAction(new RecordedLabelAction(currentLabel(run)));
        }

        /**
         * The label of the node executing this run.
         *
         * <p>An empty string when the node cannot be determined, which the estimator treats as a
         * label mismatch rather than a match, so an unknown label never inflates similarity.
         */
        private static String currentLabel(Run<?, ?> run) {
            hudson.model.Executor executor = run.getExecutor();
            if (executor == null) {
                return "";
            }
            Node node = executor.getOwner().getNode();
            if (node == null) {
                return "";
            }
            String assigned = node.getLabelString();
            if (assigned != null && !assigned.isBlank()) {
                return assigned.trim();
            }
            // The controller has no label string of its own.
            Jenkins jenkins = Jenkins.getInstanceOrNull();
            return jenkins != null && node == jenkins ? "built-in" : node.getNodeName();
        }
    }
}
