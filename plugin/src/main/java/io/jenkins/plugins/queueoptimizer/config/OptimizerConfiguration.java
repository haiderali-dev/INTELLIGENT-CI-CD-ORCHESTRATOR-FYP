package io.jenkins.plugins.queueoptimizer.config;

import edu.umd.cs.findbugs.annotations.CheckForNull;
import edu.umd.cs.findbugs.annotations.NonNull;
import hudson.Extension;
import hudson.util.FormValidation;
import hudson.util.Secret;
import jenkins.model.GlobalConfiguration;
import org.jenkinsci.Symbol;
import org.kohsuke.stapler.DataBoundSetter;
import org.kohsuke.stapler.QueryParameter;

/**
 * Global configuration for the optimizer, at Manage Jenkins &gt; Dynamic Queue Optimizer.
 *
 * <p>Every default comes from report Appendix D. The {@link Symbol} makes the whole block settable
 * through Configuration as Code:
 *
 * <pre>
 * unclassified:
 *   dynamicQueueOptimizer:
 *     optimizerEnabled: true
 *     weightUrgency: 0.5
 * </pre>
 *
 * <p>{@code optimizerEnabled: false} is how the experiment's observe-only baseline arm runs: the
 * sorter stops reordering but the metrics recorders keep working, so both arms are measured by
 * exactly the same code. That is deliberately different from Milestone 2, whose baseline was a
 * separate Jenkins home with the plugin absent, leaving the measurement path itself uncontrolled.
 */
@Extension
@Symbol("dynamicQueueOptimizer")
public class OptimizerConfiguration extends GlobalConfiguration {

    // --- Report Appendix D defaults. Changing one of these changes published results. ---
    private static final double DEFAULT_WEIGHT_URGENCY = 0.5;
    private static final double DEFAULT_WEIGHT_DEPENDENCY = 0.3;
    private static final double DEFAULT_WEIGHT_EXECUTION_TIME = 0.2;
    private static final double DEFAULT_AGING_BONUS = 0.05;
    private static final int DEFAULT_AGING_INTERVAL_MINUTES = 5;
    private static final double DEFAULT_AGING_CAP = 0.15;
    private static final int DEFAULT_ESTIMATOR_K = 5;
    private static final double DEFAULT_SIMILARITY_THRESHOLD = 0.35;
    private static final double DEFAULT_RECENCY_LAMBDA_PER_DAY = 0.1;
    private static final int DEFAULT_HISTORY_WINDOW = 50;
    private static final int DEFAULT_RESCORE_INTERVAL_SECONDS = 60;

    /** Weights are expected to sum to this, within {@link #WEIGHT_SUM_TOLERANCE}. */
    private static final double EXPECTED_WEIGHT_SUM = 1.0;

    private static final double WEIGHT_SUM_TOLERANCE = 1e-6;

    private double weightUrgency = DEFAULT_WEIGHT_URGENCY;
    private double weightDependency = DEFAULT_WEIGHT_DEPENDENCY;
    private double weightExecutionTime = DEFAULT_WEIGHT_EXECUTION_TIME;
    private double agingBonusPerInterval = DEFAULT_AGING_BONUS;
    private int agingIntervalMinutes = DEFAULT_AGING_INTERVAL_MINUTES;
    private double agingCap = DEFAULT_AGING_CAP;
    private int estimatorK = DEFAULT_ESTIMATOR_K;
    private double similarityThreshold = DEFAULT_SIMILARITY_THRESHOLD;
    private double recencyLambdaPerDay = DEFAULT_RECENCY_LAMBDA_PER_DAY;
    private int historyWindow = DEFAULT_HISTORY_WINDOW;
    private int rescoreIntervalSeconds = DEFAULT_RESCORE_INTERVAL_SECONDS;
    private boolean metricsEnabled = true;

    /**
     * Empty by default, which means metrics are not published anywhere.
     *
     * <p>Report Appendix D shows {@code http://backend:8000/api/metrics} as the default. That is
     * wrong for a fresh install, which would then post to a host that need not exist. The JCasC
     * files set the real URL. See {@code docs/decisions.md} D-006.
     */
    private String metricsBackendUrl = "";

    @CheckForNull
    private Secret metricsToken;

    private boolean optimizerEnabled = true;

    public OptimizerConfiguration() {
        load();
    }

    /** @return the singleton, or a defaults-only instance when Jenkins is not running */
    @NonNull
    public static OptimizerConfiguration get() {
        OptimizerConfiguration config = GlobalConfiguration.all().get(OptimizerConfiguration.class);
        return config == null ? new OptimizerConfiguration() : config;
    }

    // --- Weights -----------------------------------------------------------------

    public double getWeightUrgency() {
        return weightUrgency;
    }

    @DataBoundSetter
    public void setWeightUrgency(double weightUrgency) {
        this.weightUrgency = weightUrgency;
        save();
    }

    public double getWeightDependency() {
        return weightDependency;
    }

    @DataBoundSetter
    public void setWeightDependency(double weightDependency) {
        this.weightDependency = weightDependency;
        save();
    }

    public double getWeightExecutionTime() {
        return weightExecutionTime;
    }

    @DataBoundSetter
    public void setWeightExecutionTime(double weightExecutionTime) {
        this.weightExecutionTime = weightExecutionTime;
        save();
    }

    // --- Aging -------------------------------------------------------------------

    public double getAgingBonusPerInterval() {
        return agingBonusPerInterval;
    }

    @DataBoundSetter
    public void setAgingBonusPerInterval(double agingBonusPerInterval) {
        this.agingBonusPerInterval = agingBonusPerInterval;
        save();
    }

    public int getAgingIntervalMinutes() {
        return agingIntervalMinutes;
    }

    @DataBoundSetter
    public void setAgingIntervalMinutes(int agingIntervalMinutes) {
        this.agingIntervalMinutes = agingIntervalMinutes;
        save();
    }

    public double getAgingCap() {
        return agingCap;
    }

    @DataBoundSetter
    public void setAgingCap(double agingCap) {
        this.agingCap = agingCap;
        save();
    }

    // --- Estimator ---------------------------------------------------------------

    public int getEstimatorK() {
        return estimatorK;
    }

    @DataBoundSetter
    public void setEstimatorK(int estimatorK) {
        this.estimatorK = estimatorK;
        save();
    }

    public double getSimilarityThreshold() {
        return similarityThreshold;
    }

    @DataBoundSetter
    public void setSimilarityThreshold(double similarityThreshold) {
        this.similarityThreshold = similarityThreshold;
        save();
    }

    public double getRecencyLambdaPerDay() {
        return recencyLambdaPerDay;
    }

    @DataBoundSetter
    public void setRecencyLambdaPerDay(double recencyLambdaPerDay) {
        this.recencyLambdaPerDay = recencyLambdaPerDay;
        save();
    }

    public int getHistoryWindow() {
        return historyWindow;
    }

    @DataBoundSetter
    public void setHistoryWindow(int historyWindow) {
        this.historyWindow = historyWindow;
        save();
    }

    // --- Scheduling and metrics --------------------------------------------------

    public int getRescoreIntervalSeconds() {
        return rescoreIntervalSeconds;
    }

    @DataBoundSetter
    public void setRescoreIntervalSeconds(int rescoreIntervalSeconds) {
        this.rescoreIntervalSeconds = rescoreIntervalSeconds;
        save();
    }

    public boolean isMetricsEnabled() {
        return metricsEnabled;
    }

    @DataBoundSetter
    public void setMetricsEnabled(boolean metricsEnabled) {
        this.metricsEnabled = metricsEnabled;
        save();
    }

    @NonNull
    public String getMetricsBackendUrl() {
        return metricsBackendUrl == null ? "" : metricsBackendUrl;
    }

    @DataBoundSetter
    public void setMetricsBackendUrl(@CheckForNull String metricsBackendUrl) {
        this.metricsBackendUrl = metricsBackendUrl == null ? "" : metricsBackendUrl.trim();
        save();
    }

    @CheckForNull
    public Secret getMetricsToken() {
        return metricsToken;
    }

    @DataBoundSetter
    public void setMetricsToken(@CheckForNull Secret metricsToken) {
        this.metricsToken = metricsToken;
        save();
    }

    public boolean isOptimizerEnabled() {
        return optimizerEnabled;
    }

    @DataBoundSetter
    public void setOptimizerEnabled(boolean optimizerEnabled) {
        this.optimizerEnabled = optimizerEnabled;
        save();
    }

    // --- Derived -----------------------------------------------------------------

    /** @return true when the three weights sum to 1.0 within tolerance */
    public boolean weightsSumToOne() {
        double sum = weightUrgency + weightDependency + weightExecutionTime;
        return Math.abs(sum - EXPECTED_WEIGHT_SUM) < WEIGHT_SUM_TOLERANCE;
    }

    /** @return true when metrics should actually be published somewhere */
    public boolean isMetricsPublishable() {
        return metricsEnabled && !getMetricsBackendUrl().isEmpty();
    }

    // --- Form validation ---------------------------------------------------------

    /**
     * Rejects negative weights and warns when the three do not sum to 1.0.
     *
     * <p>A warning rather than an error on purpose: the report's ablation study varies the weights,
     * and the formula stays meaningful when they sum to something else, merely no longer normalised
     * to [0, 1]. Blocking it would block a legitimate experiment.
     */
    public FormValidation doCheckWeightUrgency(@QueryParameter double value) {
        return validateWeight(value);
    }

    public FormValidation doCheckWeightDependency(@QueryParameter double value) {
        return validateWeight(value);
    }

    public FormValidation doCheckWeightExecutionTime(@QueryParameter double value) {
        return validateWeight(value);
    }

    private FormValidation validateWeight(double value) {
        if (value < 0) {
            return FormValidation.error("A weight cannot be negative.");
        }
        if (!weightsSumToOne()) {
            double sum = weightUrgency + weightDependency + weightExecutionTime;
            return FormValidation.warning(
                    "The three weights currently sum to %.3f rather than 1.0, so scores will not "
                            + "be normalised to [0, 1]. The report's formula uses 0.5, 0.3, 0.2.",
                    sum);
        }
        return FormValidation.ok();
    }

    public FormValidation doCheckAgingBonusPerInterval(@QueryParameter double value) {
        return nonNegative(value);
    }

    public FormValidation doCheckAgingCap(@QueryParameter double value) {
        return nonNegative(value);
    }

    public FormValidation doCheckSimilarityThreshold(@QueryParameter double value) {
        if (value < 0 || value > 1) {
            return FormValidation.error("A similarity threshold must be between 0 and 1.");
        }
        return FormValidation.ok();
    }

    public FormValidation doCheckRecencyLambdaPerDay(@QueryParameter double value) {
        return nonNegative(value);
    }

    public FormValidation doCheckAgingIntervalMinutes(@QueryParameter int value) {
        return strictlyPositive(value, "The aging interval must be at least one minute.");
    }

    public FormValidation doCheckEstimatorK(@QueryParameter int value) {
        return strictlyPositive(value, "k must be at least 1.");
    }

    public FormValidation doCheckHistoryWindow(@QueryParameter int value) {
        return strictlyPositive(value, "The history window must be at least 1 build.");
    }

    public FormValidation doCheckRescoreIntervalSeconds(@QueryParameter int value) {
        return strictlyPositive(value, "The rescore interval must be at least one second.");
    }

    private static FormValidation nonNegative(double value) {
        return value < 0 ? FormValidation.error("This value cannot be negative.") : FormValidation.ok();
    }

    private static FormValidation strictlyPositive(int value, String message) {
        return value < 1 ? FormValidation.error(message) : FormValidation.ok();
    }
}
