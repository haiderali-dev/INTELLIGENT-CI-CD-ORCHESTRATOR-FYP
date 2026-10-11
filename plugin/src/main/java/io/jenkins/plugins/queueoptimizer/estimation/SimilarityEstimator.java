package io.jenkins.plugins.queueoptimizer.estimation;

import java.util.Collection;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.OptionalLong;
import java.util.Set;

/**
 * Report Algorithm 6.4: recency-weighted top-k similarity estimation.
 *
 * <pre>
 * sim      = 0.5 * jaccard(nameTokens) + 0.3 * jaccard(params) + 0.2 * (labels equal ? 1 : 0)
 * keep builds with sim &gt;= similarityThreshold, take the top k
 * weight_b = sim * exp(-recencyLambdaPerDay * ageDays)
 * estimate = sum(weight_b * duration_b) / sum(weight_b)
 * no candidates -&gt; UNKNOWN
 * </pre>
 *
 * <p>An instance-based k-NN method rather than the job's own average, because the SaaS scenario
 * this project models has many near-identical pipelines and a brand new job must still get a
 * usable estimate from its siblings. When a job has run before, its own builds dominate anyway,
 * since their name similarity is 1.0.
 *
 * <p>Returning UNKNOWN rather than guessing is deliberate: the scorer maps it to the neutral
 * factor 0.5, so a job with no history is neither punished nor favoured. Milestone 2's estimator
 * fell back to the job's last build ever, which made one anomalous run distort every future
 * decision.
 *
 * <p>No Jenkins imports, so the maths is directly testable.
 */
public final class SimilarityEstimator {

    private static final double WEIGHT_NAME = 0.5;
    private static final double WEIGHT_PARAMS = 0.3;
    private static final double WEIGHT_LABEL = 0.2;

    private final int k;
    private final double similarityThreshold;
    private final double recencyLambdaPerDay;

    public SimilarityEstimator(int k, double similarityThreshold, double recencyLambdaPerDay) {
        this.k = k;
        this.similarityThreshold = similarityThreshold;
        this.recencyLambdaPerDay = recencyLambdaPerDay;
    }

    /** An estimator using the report Appendix D defaults: k = 5, threshold 0.35, lambda 0.1/day. */
    public static SimilarityEstimator withReportDefaults() {
        return new SimilarityEstimator(5, 0.35, 0.1);
    }

    /**
     * Estimates how long {@code target} will take, from history.
     *
     * @param target the job about to run, as a feature record; its duration and age are ignored
     * @param history candidate past builds
     * @return the estimate in milliseconds, or empty when nothing clears the threshold
     */
    public OptionalLong estimate(BuildRecord target, Collection<BuildRecord> history) {
        if (history == null || history.isEmpty()) {
            return OptionalLong.empty();
        }

        List<Candidate> candidates = history.stream()
                .map(build -> new Candidate(build, similarity(target, build)))
                .filter(c -> c.similarity >= similarityThreshold)
                .sorted(Comparator.comparingDouble((Candidate c) -> c.similarity)
                        .reversed()
                        // A stable tie-break so an estimate does not wander between passes.
                        .thenComparingDouble(c -> c.build.ageDays())
                        .thenComparing(c -> c.build.jobName()))
                .limit(k)
                .toList();

        if (candidates.isEmpty()) {
            return OptionalLong.empty();
        }

        double weightedSum = 0;
        double totalWeight = 0;
        for (Candidate candidate : candidates) {
            double weight = candidate.similarity * Math.exp(-recencyLambdaPerDay * candidate.build.ageDays());
            weightedSum += weight * candidate.build.durationMillis();
            totalWeight += weight;
        }

        if (totalWeight <= 0) {
            // Every candidate decayed to nothing. Claiming an estimate here would be inventing one.
            return OptionalLong.empty();
        }
        return OptionalLong.of(Math.round(weightedSum / totalWeight));
    }

    /**
     * The similarity of two builds, in [0, 1].
     *
     * <p>Name similarity dominates at 0.5, so {@code build-payment-service} and
     * {@code test-payment-service} are related but not interchangeable.
     */
    public static double similarity(BuildRecord a, BuildRecord b) {
        double nameSimilarity = jaccard(a.nameTokens(), b.nameTokens());
        double paramSimilarity = jaccard(a.parameterSignatures(), b.parameterSignatures());
        double labelSimilarity = a.agentLabel().equals(b.agentLabel()) ? 1.0 : 0.0;
        return WEIGHT_NAME * nameSimilarity + WEIGHT_PARAMS * paramSimilarity + WEIGHT_LABEL * labelSimilarity;
    }

    /**
     * Jaccard index: intersection over union.
     *
     * <p>Two empty sets count as identical. That is the right reading for parameters, where
     * "neither build takes parameters" is a genuine match rather than missing information, and it
     * keeps an unparameterised job from being penalised against its own history.
     */
    public static double jaccard(Set<String> a, Set<String> b) {
        if (a.isEmpty() && b.isEmpty()) {
            return 1.0;
        }
        if (a.isEmpty() || b.isEmpty()) {
            return 0.0;
        }
        Set<String> intersection = new HashSet<>(a);
        intersection.retainAll(b);
        Set<String> union = new HashSet<>(a);
        union.addAll(b);
        return (double) intersection.size() / union.size();
    }

    private record Candidate(BuildRecord build, double similarity) {}
}
