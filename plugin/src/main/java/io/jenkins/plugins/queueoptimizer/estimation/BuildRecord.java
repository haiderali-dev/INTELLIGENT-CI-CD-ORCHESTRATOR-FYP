package io.jenkins.plugins.queueoptimizer.estimation;

import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * One historical build, reduced to the features the estimator compares.
 *
 * <p>Plain data with no Jenkins imports, so the similarity maths can be tested directly.
 * {@code BuildHistoryService} is what turns real {@code Run} objects into these.
 *
 * @param jobName the job's full name
 * @param nameTokens the job name split on {@code [-_\s]} and lowercased
 * @param parameterSignatures parameter name/value pairs, as {@code name=value}
 * @param agentLabel the label of the node the build actually ran on, empty when unknown
 * @param durationMillis how long the build took
 * @param ageDays how long ago it finished, in days
 */
public record BuildRecord(
        String jobName,
        Set<String> nameTokens,
        Set<String> parameterSignatures,
        String agentLabel,
        long durationMillis,
        double ageDays) {

    /** Splits a job name into comparison tokens, per report Algorithm 6.4. */
    public static Set<String> tokenize(String jobName) {
        if (jobName == null || jobName.isBlank()) {
            return Set.of();
        }
        return Arrays.stream(jobName.split("[-_\\s/]+"))
                .map(token -> token.toLowerCase(Locale.ROOT))
                .filter(token -> !token.isEmpty())
                .collect(Collectors.toCollection(LinkedHashSet::new));
    }

    /** Renders parameters as {@code name=value} strings for set comparison. */
    public static Set<String> signatures(Map<String, String> parameters) {
        if (parameters == null || parameters.isEmpty()) {
            return Set.of();
        }
        return parameters.entrySet().stream()
                .map(e -> e.getKey() + "=" + e.getValue())
                .collect(Collectors.toCollection(LinkedHashSet::new));
    }

    /** Builds a record from a job name and parameter map, doing the tokenising. */
    public static BuildRecord of(
            String jobName, Map<String, String> parameters, String agentLabel, long durationMillis, double ageDays) {
        return new BuildRecord(
                jobName,
                tokenize(jobName),
                signatures(parameters),
                agentLabel == null ? "" : agentLabel,
                durationMillis,
                ageDays);
    }
}
