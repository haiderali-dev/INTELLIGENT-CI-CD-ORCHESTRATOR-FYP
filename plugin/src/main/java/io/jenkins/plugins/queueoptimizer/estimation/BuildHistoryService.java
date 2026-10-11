package io.jenkins.plugins.queueoptimizer.estimation;

import edu.umd.cs.findbugs.annotations.NonNull;
import hudson.model.Job;
import hudson.model.ParameterValue;
import hudson.model.ParametersAction;
import hudson.model.Run;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import jenkins.model.Jenkins;

/**
 * Reads recent build history and reduces it to the feature records the estimator compares.
 *
 * <p>The Jenkins-facing half of report Algorithm 6.4; {@link SimilarityEstimator} holds the maths
 * and stays free of Jenkins imports so it can be tested directly.
 *
 * <p>History is read per pass and handed to the estimator as a list, so one traversal serves
 * every item in the queue. Milestone 2 re-read history inside the per-peer loop of a per-item
 * calculation, which is how its scoring reached O(n³).
 */
public final class BuildHistoryService {

    private BuildHistoryService() {}

    /**
     * The most recent completed builds across all jobs, newest first.
     *
     * @param historyWindow how many builds to read per job
     * @return feature records, possibly empty, never null
     */
    @NonNull
    public static List<BuildRecord> recentBuilds(int historyWindow) {
        Jenkins jenkins = Jenkins.getInstanceOrNull();
        if (jenkins == null || historyWindow <= 0) {
            return List.of();
        }

        long now = System.currentTimeMillis();
        List<BuildRecord> records = new ArrayList<>();
        for (Job<?, ?> job : jenkins.getAllItems(Job.class)) {
            int taken = 0;
            for (Run<?, ?> run : job.getBuilds()) {
                if (taken >= historyWindow) {
                    break;
                }
                if (run.isBuilding() || run.getDuration() <= 0) {
                    // An in-flight or zero-duration build tells us nothing about how long the
                    // work takes.
                    continue;
                }
                records.add(toRecord(job, run, now));
                taken++;
            }
        }
        return records;
    }

    /**
     * The feature record describing a job that is about to run.
     *
     * <p>Duration and age are meaningless for a job that has not run yet and are left at zero;
     * the estimator ignores them on the target.
     */
    @NonNull
    public static BuildRecord featuresOf(@NonNull Job<?, ?> job) {
        Run<?, ?> last = job.getLastBuild();
        String label = last == null ? "" : agentLabelOf(last);
        return BuildRecord.of(job.getFullName(), lastParameters(job), label, 0L, 0.0);
    }

    private static BuildRecord toRecord(Job<?, ?> job, Run<?, ?> run, long now) {
        double ageDays = Math.max(0.0, (now - run.getStartTimeInMillis()) / 86_400_000.0);
        return BuildRecord.of(job.getFullName(), parametersOf(run), agentLabelOf(run), run.getDuration(), ageDays);
    }

    /**
     * The label of the node a build ran on.
     *
     * <p>Read from {@link RecordedLabelAction}, written when the build started. The node itself
     * may have been removed or relabelled since, so the label is recorded at build time rather
     * than looked up afterwards.
     */
    @NonNull
    static String agentLabelOf(Run<?, ?> run) {
        RecordedLabelAction action = run.getAction(RecordedLabelAction.class);
        return action == null ? "" : action.getLabel();
    }

    @NonNull
    private static Map<String, String> parametersOf(Run<?, ?> run) {
        ParametersAction action = run.getAction(ParametersAction.class);
        if (action == null) {
            return Map.of();
        }
        Map<String, String> parameters = new LinkedHashMap<>();
        for (ParameterValue value : action.getParameters()) {
            Object raw = value.getValue();
            parameters.put(value.getName(), raw == null ? "" : String.valueOf(raw));
        }
        return parameters;
    }

    @NonNull
    private static Map<String, String> lastParameters(Job<?, ?> job) {
        Run<?, ?> last = job.getLastBuild();
        return last == null ? Map.of() : parametersOf(last);
    }
}
