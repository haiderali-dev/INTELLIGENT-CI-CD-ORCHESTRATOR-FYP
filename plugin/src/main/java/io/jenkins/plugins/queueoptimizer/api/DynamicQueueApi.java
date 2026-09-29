package io.jenkins.plugins.queueoptimizer.api;

import edu.umd.cs.findbugs.annotations.CheckForNull;
import edu.umd.cs.findbugs.annotations.NonNull;
import hudson.Extension;
import hudson.model.Job;
import hudson.model.Queue;
import hudson.model.RootAction;
import hudson.model.queue.CauseOfBlockage;
import io.jenkins.plugins.queueoptimizer.config.OptimizerConfiguration;
import io.jenkins.plugins.queueoptimizer.gate.DependencyGate;
import io.jenkins.plugins.queueoptimizer.metrics.MetricEvent;
import io.jenkins.plugins.queueoptimizer.metrics.MetricsPublisher;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import io.jenkins.plugins.queueoptimizer.resolve.JobResolver;
import io.jenkins.plugins.queueoptimizer.scoring.PriorityScoreCalculator;
import io.jenkins.plugins.queueoptimizer.scoring.ScoredJob;
import io.jenkins.plugins.queueoptimizer.sorter.DynamicQueueSorter;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.StringJoiner;
import javax.servlet.http.HttpServletResponse;
import jenkins.model.Jenkins;
import org.kohsuke.stapler.StaplerRequest;
import org.kohsuke.stapler.StaplerResponse;

/**
 * Read-only HTTP endpoints exposing what the optimizer decided and why.
 *
 * <ul>
 *   <li>{@code GET /dynamic-queue/api/json} — the configuration in force, and every buildable item
 *       with its rank, score components, estimate, wait, group and blocked reason.
 *   <li>{@code GET /dynamic-queue/metrics/recent?limit=N} — the last N recorded events.
 *   <li>{@code GET /dynamic-queue/health} — enabled flag, last sort duration, cache hit rate and
 *       dropped metric count.
 * </ul>
 *
 * <p>Every endpoint requires {@code Jenkins.READ}. The queue reveals job names and timing, which is
 * information about work in progress, so it is not anonymous-readable even though it changes
 * nothing.
 *
 * <p>The ranking endpoint returns the score's components, not just the total. That is what lets the
 * frontend's score bar answer "why is my build not running yet" and what lets the experiment
 * harness verify a ranking independently rather than trusting it.
 */
@Extension
public class DynamicQueueApi implements RootAction {

    private static final int DEFAULT_RECENT_LIMIT = 100;
    private static final int MAX_RECENT_LIMIT = 500;

    @CheckForNull
    @Override
    public String getIconFileName() {
        // No sidebar entry; this is a machine-facing endpoint.
        return null;
    }

    @CheckForNull
    @Override
    public String getDisplayName() {
        return null;
    }

    @NonNull
    @Override
    public String getUrlName() {
        return "dynamic-queue";
    }

    /**
     * Routes {@code /dynamic-queue/api/...}.
     *
     * <p>Stapler matches one path segment per method, so a multi-segment path needs an
     * intermediate object: {@code api} resolves here, then {@code json} resolves to
     * {@link ApiEndpoint#doJson}. A single {@code @WebMethod(name = "api/json")} silently 404s,
     * which is how this was found.
     */
    public ApiEndpoint getApi() {
        return new ApiEndpoint(this);
    }

    /** Routes {@code /dynamic-queue/metrics/recent}. */
    public MetricsEndpoint getMetrics() {
        return new MetricsEndpoint(this);
    }

    /** {@code GET /dynamic-queue/api/json}: the current ranking with full score breakdowns. */
    void writeRanking(StaplerRequest request, StaplerResponse response) throws IOException {
        Jenkins jenkins = Jenkins.get();
        jenkins.checkPermission(Jenkins.READ);

        OptimizerConfiguration config = OptimizerConfiguration.get();
        List<Queue.BuildableItem> buildable = jenkins.getQueue().getBuildableItems();

        // Rank by the same comparator the sorter uses, from the scores it recorded, so the API can
        // never report an order the scheduler did not actually apply.
        List<ScoredJob> scored = new ArrayList<>();
        for (Queue.BuildableItem item : buildable) {
            DynamicQueueSorter.getHeap().get(item.getId()).ifPresent(scored::add);
        }
        scored.sort(PriorityScoreCalculator.compareForDispatch());

        StringJoiner items = new StringJoiner(",", "[", "]");
        for (int rank = 0; rank < scored.size(); rank++) {
            items.add(renderItem(scored.get(rank), rank + 1, buildable));
        }

        // Items the sorter could not score still appear, with a null rank, so the endpoint never
        // silently omits queued work.
        StringJoiner unscored = new StringJoiner(",", "[", "]");
        for (Queue.BuildableItem item : buildable) {
            if (DynamicQueueSorter.getHeap().get(item.getId()).isEmpty()) {
                unscored.add("{" + pair("itemId", item.getId())
                        + "," + pairString("jobName", JobResolver.describe(item))
                        + "," + pairString("reason", "not scored by the optimizer")
                        + "}");
            }
        }

        write(
                response,
                "{\"configuration\":" + renderConfig(config)
                        + ",\"queueLength\":" + buildable.size()
                        + ",\"items\":" + items
                        + ",\"unscoredItems\":" + unscored
                        + "}");
    }

    /** {@code GET /dynamic-queue/metrics/recent?limit=N}: the last N recorded events. */
    void writeRecentMetrics(StaplerRequest request, StaplerResponse response) throws IOException {
        Jenkins.get().checkPermission(Jenkins.READ);

        int limit = DEFAULT_RECENT_LIMIT;
        String raw = request.getParameter("limit");
        if (raw != null && !raw.isBlank()) {
            try {
                limit = Math.max(1, Math.min(MAX_RECENT_LIMIT, Integer.parseInt(raw.trim())));
            } catch (NumberFormatException notANumber) {
                response.sendError(HttpServletResponse.SC_BAD_REQUEST, "limit must be an integer");
                return;
            }
        }

        MetricsPublisher publisher = MetricsPublisher.get();
        StringJoiner events = new StringJoiner(",", "[", "]");
        for (MetricEvent event : publisher.getRecent(limit)) {
            events.add(event.toJson());
        }

        write(response, "{\"limit\":" + limit + ",\"events\":" + events + "}");
    }

    /**
     * {@code GET /dynamic-queue/health}: enabled, last sort duration, cache hit rate, drops.
     *
     * <p>No annotation needed: Stapler derives the single path segment {@code health} from the
     * method name.
     */
    public void doHealth(StaplerRequest request, StaplerResponse response) throws IOException {
        Jenkins.get().checkPermission(Jenkins.READ);

        OptimizerConfiguration config = OptimizerConfiguration.get();
        DynamicQueueSorter sorter = DynamicQueueSorter.getInstance();
        MetricsPublisher publisher = MetricsPublisher.get();

        write(
                response,
                "{"
                        + pair("enabled", config.isOptimizerEnabled())
                        + "," + pair("lastSortDurationMillis", sorter.getLastSortDurationNanos() / 1_000_000.0)
                        + "," + pair("cacheHitRate", Math.round(sorter.getCacheHitRate() * 10_000) / 10_000.0)
                        + "," + pair("heapSize", DynamicQueueSorter.getHeap().size())
                        + "," + pair("metricsEnabled", config.isMetricsEnabled())
                        + "," + pair("metricsPublishable", config.isMetricsPublishable())
                        + "," + pair("droppedMetricCount", publisher.getDroppedCount())
                        + "," + pair("publishedMetricCount", publisher.getPublishedCount())
                        + "," + pair("failedMetricCount", publisher.getFailedCount())
                        + "," + pair("pendingMetricCount", publisher.getPendingCount())
                        + "," + pair("weightsSumToOne", config.weightsSumToOne())
                        + "}");
    }

    private static String renderItem(ScoredJob job, int rank, List<Queue.BuildableItem> buildable) {
        Optional<Queue.BuildableItem> item = buildable.stream()
                .filter(candidate -> candidate.getId() == job.itemId())
                .findFirst();

        String blockedReason = item.map(Queue.Item::getCauseOfBlockage)
                .map(CauseOfBlockage::getShortDescription)
                .orElse(null);

        StringJoiner unresolved = new StringJoiner(",", "[", "]");
        item.flatMap(JobResolver::resolve)
                .ifPresent(owner -> DependencyGate.unresolvedUpstream(owner)
                        .forEach(name -> unresolved.add(MetricEvent.jsonEscape(name))));

        StringJoiner json = new StringJoiner(",", "{", "}");
        json.add(pair("rank", rank));
        json.add(pair("itemId", job.itemId()));
        json.add(pairString("jobName", job.jobName()));
        json.add(pairString(
                "jobType",
                item.flatMap(JobResolver::resolve)
                        .map(owner -> owner.getClass().getSimpleName())
                        .orElse("unknown")));
        json.add(pairString("level", job.level().name()));
        json.add(pair("score", round(job.score())));
        json.add(pair("ownScore", round(job.ownScore())));
        json.add(pair("baseScore", round(job.baseScore())));
        json.add(pair("inheritedGroupScore", job.inheritedGroupScore()));
        // The components the score bar draws.
        json.add("\"components\":{"
                + pair("urgency", round(job.urgencyFactor()))
                + "," + pair("dependency", round(job.dependencyFactor()))
                + "," + pair("executionTime", round(job.executionTimeFactor()))
                + "," + pair("aging", round(job.agingBonus()))
                + "}");
        json.add(
                job.estimateMillis().isPresent()
                        ? pair("estimateMillis", job.estimateMillis().getAsLong())
                        : "\"estimateMillis\":null");
        json.add(pair("estimateKnown", job.estimateMillis().isPresent()));
        json.add(pair("waitSeconds", round(Math.max(0, System.currentTimeMillis() - job.inQueueSince()) / 1000.0)));
        json.add(pairString("groupId", job.groupId()));
        json.add(pair("groupSize", job.groupSize()));
        json.add(pair("topologicalRank", job.topologicalRank()));
        json.add(blockedReason == null ? "\"blockedReason\":null" : pairString("blockedReason", blockedReason));
        json.add("\"unresolvedDependencies\":" + unresolved);
        return json.toString();
    }

    private static String renderConfig(OptimizerConfiguration config) {
        StringJoiner json = new StringJoiner(",", "{", "}");
        json.add(pair("optimizerEnabled", config.isOptimizerEnabled()));
        json.add(pair("weightUrgency", config.getWeightUrgency()));
        json.add(pair("weightDependency", config.getWeightDependency()));
        json.add(pair("weightExecutionTime", config.getWeightExecutionTime()));
        json.add(pair("agingBonusPerInterval", config.getAgingBonusPerInterval()));
        json.add(pair("agingIntervalMinutes", config.getAgingIntervalMinutes()));
        json.add(pair("agingCap", config.getAgingCap()));
        json.add(pair("estimatorK", config.getEstimatorK()));
        json.add(pair("similarityThreshold", config.getSimilarityThreshold()));
        json.add(pair("recencyLambdaPerDay", config.getRecencyLambdaPerDay()));
        json.add(pair("historyWindow", config.getHistoryWindow()));
        json.add(pair("rescoreIntervalSeconds", config.getRescoreIntervalSeconds()));
        json.add(pair("metricsEnabled", config.isMetricsEnabled()));
        // The URL is configuration, not a secret. The token is never rendered.
        json.add(pairString("metricsBackendUrl", config.getMetricsBackendUrl()));
        json.add(pair("metricsTokenConfigured", config.getMetricsToken() != null));
        // Derived, but a consumer needs it: when the weights do not sum to 1.0 the scores are no
        // longer normalised to [0, 1], and a score bar drawn as if they were would mislead.
        json.add(pair("weightsSumToOne", config.weightsSumToOne()));
        return json.toString();
    }

    private static String pair(String key, Object value) {
        return MetricEvent.jsonEscape(key) + ":" + value;
    }

    private static String pairString(String key, String value) {
        return MetricEvent.jsonEscape(key) + ":" + MetricEvent.jsonEscape(value);
    }

    private static double round(double value) {
        return Math.round(value * 1_000_000d) / 1_000_000d;
    }

    private static void write(StaplerResponse response, String json) throws IOException {
        response.setContentType("application/json;charset=UTF-8");
        response.setHeader("Cache-Control", "no-store");
        response.getWriter().write(json);
    }

    /** Job names currently in the queue, for diagnostics in tests. */
    @NonNull
    static Map<Long, String> queuedJobNames() {
        Jenkins jenkins = Jenkins.get();
        Map<Long, String> names = new java.util.LinkedHashMap<>();
        for (Queue.Item item : jenkins.getQueue().getItems()) {
            names.put(
                    item.getId(),
                    JobResolver.resolve(item).map(Job::getFullName).orElse("?"));
        }
        return names;
    }

    /** The level a job would be scored at, for diagnostics in tests. */
    static String levelNameOf(Job<?, ?> job) {
        return JobPriorityProperty.levelOf(job).name();
    }

    /** The {@code api} path segment. Exists purely so Stapler can reach {@code api/json}. */
    public static class ApiEndpoint {

        private final DynamicQueueApi owner;

        ApiEndpoint(DynamicQueueApi owner) {
            this.owner = owner;
        }

        /** {@code GET /dynamic-queue/api/json}. */
        public void doJson(StaplerRequest request, StaplerResponse response) throws IOException {
            owner.writeRanking(request, response);
        }
    }

    /** The {@code metrics} path segment, so Stapler can reach {@code metrics/recent}. */
    public static class MetricsEndpoint {

        private final DynamicQueueApi owner;

        MetricsEndpoint(DynamicQueueApi owner) {
            this.owner = owner;
        }

        /** {@code GET /dynamic-queue/metrics/recent?limit=N}. */
        public void doRecent(StaplerRequest request, StaplerResponse response) throws IOException {
            owner.writeRecentMetrics(request, response);
        }
    }
}
