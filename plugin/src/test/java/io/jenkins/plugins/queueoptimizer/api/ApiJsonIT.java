package io.jenkins.plugins.queueoptimizer.api;

import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilAllComplete;
import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilBuildable;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import hudson.model.FreeStyleProject;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.util.ArrayList;
import java.util.List;
import net.sf.json.JSONArray;
import net.sf.json.JSONObject;
import org.htmlunit.Page;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.jvnet.hudson.test.JenkinsRule;
import org.jvnet.hudson.test.junit.jupiter.WithJenkins;

/**
 * Required by BUILD_PROMPT 4.3.10: the ranking endpoint returns the documented shape.
 *
 * <p>Checks the contract three consumers depend on. The backend reads the ranking to show a queue
 * page; the frontend's score bar needs the individual components, not the total; and the experiment
 * harness reads it to verify a ranking independently instead of trusting the scheduler that produced
 * it. A silently renamed field breaks all three.
 */
@WithJenkins
class ApiJsonIT {

    private static JSONObject getJson(JenkinsRule j, String path) throws Exception {
        JenkinsRule.WebClient client = j.createWebClient();
        Page page = client.goTo(path, "application/json");
        return JSONObject.fromObject(page.getWebResponse().getContentAsString());
    }

    @Test
    @DisplayName("the ranking endpoint reports the configuration in force")
    void reportsConfiguration(JenkinsRule j) throws Exception {
        JSONObject root = getJson(j, "dynamic-queue/api/json");
        JSONObject config = root.getJSONObject("configuration");

        // The report's Appendix D defaults, which the published results depend on.
        assertEquals(0.5, config.getDouble("weightUrgency"), 0.0001);
        assertEquals(0.3, config.getDouble("weightDependency"), 0.0001);
        assertEquals(0.2, config.getDouble("weightExecutionTime"), 0.0001);
        assertEquals(0.05, config.getDouble("agingBonusPerInterval"), 0.0001);
        assertEquals(5, config.getInt("agingIntervalMinutes"));
        assertEquals(0.15, config.getDouble("agingCap"), 0.0001);
        assertEquals(5, config.getInt("estimatorK"));
        assertEquals(0.35, config.getDouble("similarityThreshold"), 0.0001);
        assertEquals(0.1, config.getDouble("recencyLambdaPerDay"), 0.0001);
        assertEquals(50, config.getInt("historyWindow"));
        assertTrue(config.getBoolean("optimizerEnabled"));
        assertTrue(config.getBoolean("weightsSumToOne"));
    }

    @Test
    @DisplayName("the metrics token is never rendered, only whether one is set")
    void tokenIsNeverExposed(JenkinsRule j) throws Exception {
        JSONObject config = getJson(j, "dynamic-queue/api/json").getJSONObject("configuration");

        assertFalse(config.has("metricsToken"), "a Secret must never reach an HTTP response");
        assertTrue(config.has("metricsTokenConfigured"), "whether one is set is still useful");
        assertTrue(config.has("metricsBackendUrl"), "the URL is configuration, not a secret");
    }

    @Test
    @DisplayName("each queued item carries its rank, score, components and group")
    void itemsCarryTheFullBreakdown(JenkinsRule j) throws Exception {
        j.jenkins.setNumExecutors(0);
        schedule(j, "api-low", "LOW");
        schedule(j, "api-high", "HIGH");
        waitUntilBuildable(j, 2);

        // Force a sort so the heap holds scores for these items.
        j.jenkins.getQueue().maintain();

        JSONObject root = getJson(j, "dynamic-queue/api/json");
        assertEquals(2, root.getInt("queueLength"));

        JSONArray items = root.getJSONArray("items");
        assertEquals(2, items.size(), "both queued items must appear");

        JSONObject first = items.getJSONObject(0);
        assertEquals(1, first.getInt("rank"), "ranks start at 1");
        assertEquals("api-high", first.getString("jobName"), "HIGH must rank first");
        assertEquals("HIGH", first.getString("level"));

        for (String field : List.of(
                "rank",
                "itemId",
                "jobName",
                "jobType",
                "level",
                "score",
                "ownScore",
                "baseScore",
                "inheritedGroupScore",
                "components",
                "estimateMillis",
                "estimateKnown",
                "waitSeconds",
                "groupId",
                "groupSize",
                "topologicalRank",
                "blockedReason",
                "unresolvedDependencies")) {
            assertTrue(first.has(field), "the documented field '" + field + "' is missing");
        }

        JSONObject components = first.getJSONObject("components");
        for (String component : List.of("urgency", "dependency", "executionTime", "aging")) {
            assertTrue(components.has(component), "score bar component '" + component + "' missing");
        }
        assertEquals(1.0, components.getDouble("urgency"), 0.0001, "HIGH maps to 1.0");

        j.jenkins.setNumExecutors(2);
        waitUntilAllComplete(j, List.of("api-low", "api-high"));
    }

    @Test
    @DisplayName("items are listed in the order the sorter would dispatch them")
    void itemsAreListedInDispatchOrder(JenkinsRule j) throws Exception {
        j.jenkins.setNumExecutors(0);
        schedule(j, "ord-low", "LOW");
        schedule(j, "ord-medium", "MEDIUM");
        schedule(j, "ord-high", "HIGH");
        waitUntilBuildable(j, 3);
        j.jenkins.getQueue().maintain();

        JSONArray items = getJson(j, "dynamic-queue/api/json").getJSONArray("items");
        List<String> names = new ArrayList<>();
        for (int i = 0; i < items.size(); i++) {
            names.add(items.getJSONObject(i).getString("jobName"));
        }

        assertEquals(
                List.of("ord-high", "ord-medium", "ord-low"),
                names,
                "the API must never report an order the scheduler did not apply");

        j.jenkins.setNumExecutors(3);
        waitUntilAllComplete(j, List.of("ord-low", "ord-medium", "ord-high"));
    }

    @Test
    @DisplayName("an unresolved dependency is reported on the item")
    void unresolvedDependenciesAreReported(JenkinsRule j) throws Exception {
        j.jenkins.setNumExecutors(0);
        FreeStyleProject project = j.createFreeStyleProject("api-ghost-dep");
        project.addProperty(new JobPriorityProperty("MEDIUM", "no-such-upstream"));
        project.scheduleBuild2(0);
        // A second item, so the sorter actually runs: it returns early below two items.
        schedule(j, "api-filler", "MEDIUM");
        waitUntilBuildable(j, 2);
        j.jenkins.getQueue().maintain();

        JSONArray items = getJson(j, "dynamic-queue/api/json").getJSONArray("items");
        JSONObject ghost = null;
        for (int i = 0; i < items.size(); i++) {
            if ("api-ghost-dep".equals(items.getJSONObject(i).getString("jobName"))) {
                ghost = items.getJSONObject(i);
            }
        }
        assertNotNull(ghost, "the item with the bad dependency should still be listed");
        assertEquals(
                List.of("no-such-upstream"),
                ghost.getJSONArray("unresolvedDependencies").stream()
                        .map(String::valueOf)
                        .toList(),
                "a typo must be visible, not merely ineffective");

        j.jenkins.setNumExecutors(2);
        waitUntilAllComplete(j, List.of("api-ghost-dep", "api-filler"));
    }

    @Test
    @DisplayName("the health endpoint reports the operational counters")
    void healthReportsCounters(JenkinsRule j) throws Exception {
        JSONObject health = getJson(j, "dynamic-queue/health");

        for (String field : List.of(
                "enabled",
                "lastSortDurationMillis",
                "cacheHitRate",
                "heapSize",
                "metricsEnabled",
                "metricsPublishable",
                "droppedMetricCount",
                "publishedMetricCount",
                "failedMetricCount",
                "pendingMetricCount",
                "weightsSumToOne")) {
            assertTrue(health.has(field), "health field '" + field + "' missing");
        }
        assertTrue(health.getBoolean("enabled"));
        assertEquals(0, health.getLong("droppedMetricCount"));
        assertFalse(
                health.getBoolean("metricsPublishable"),
                "with no backend URL configured, nothing should be publishable");
    }

    @Test
    @DisplayName("the recent-metrics endpoint returns events and honours its limit")
    void recentMetricsEndpoint(JenkinsRule j) throws Exception {
        j.buildAndAssertSuccess(j.createFreeStyleProject("metrics-source"));

        JSONObject root = getJson(j, "dynamic-queue/metrics/recent?limit=5");
        assertEquals(5, root.getInt("limit"));

        JSONArray events = root.getJSONArray("events");
        assertTrue(events.size() <= 5, "the limit must be respected");
        assertFalse(events.isEmpty(), "running a build should have recorded something");

        JSONObject event = events.getJSONObject(events.size() - 1);
        assertTrue(event.has("kind"));
        assertTrue(event.has("timestamp"));
    }

    @Test
    @DisplayName("a non-numeric limit is rejected rather than silently defaulted")
    void badLimitIsRejected(JenkinsRule j) throws Exception {
        JenkinsRule.WebClient client = j.createWebClient();
        client.getOptions().setThrowExceptionOnFailingStatusCode(false);

        Page page = client.goTo("dynamic-queue/metrics/recent?limit=abc", null);

        assertEquals(
                HttpURLConnection.HTTP_BAD_REQUEST,
                page.getWebResponse().getStatusCode(),
                "silently defaulting a malformed parameter hides a caller's bug");
    }

    @Test
    @DisplayName("every endpoint requires authentication when anonymous read is denied")
    void endpointsRequireRead(JenkinsRule j) throws Exception {
        // The queue reveals job names and timings, which is information about work in progress.
        j.jenkins.setSecurityRealm(j.createDummySecurityRealm());
        j.jenkins.setAuthorizationStrategy(new org.jvnet.hudson.test.MockAuthorizationStrategy()
                .grant(jenkins.model.Jenkins.READ)
                .everywhere()
                .to("developer"));

        JenkinsRule.WebClient anonymous = j.createWebClient();
        anonymous.getOptions().setThrowExceptionOnFailingStatusCode(false);
        anonymous.getOptions().setRedirectEnabled(false);

        for (String path : List.of("dynamic-queue/api/json", "dynamic-queue/health")) {
            Page denied = anonymous.goTo(path, null);
            int status = denied.getWebResponse().getStatusCode();
            String body = denied.getWebResponse().getContentAsString();

            // The assertion that matters is that the payload is withheld, and it is deliberately
            // the only one made here. Jenkins may answer an unauthorised browser client with a
            // redirect, a 403, or an empty 200 depending on the filter chain and the Accept
            // header, so pinning the denial mechanism would make this test fail on Jenkins
            // upgrades that changed nothing about the plugin. The paired authenticated request
            // below is what proves the endpoint is reachable at all, which together with this
            // makes it a real permission test rather than a test that the URL is broken.
            assertFalse(
                    body.contains("\"configuration\"") || body.contains("\"heapSize\""),
                    path + " leaked its payload to an anonymous caller (status " + status + "): "
                            + body.substring(0, Math.min(200, body.length())));
        }

        // The other half of the differential: a caller who does hold READ gets the full payload.
        // Without this, the test above would pass just as happily against a 404.
        JenkinsRule.WebClient reader = j.createWebClient().login("developer");

        JSONObject health = JSONObject.fromObject(reader.goTo("dynamic-queue/health", "application/json")
                .getWebResponse()
                .getContentAsString());
        assertTrue(health.has("enabled"), "a reader must receive the health payload");
        assertTrue(health.has("heapSize"));

        JSONObject ranking = JSONObject.fromObject(reader.goTo("dynamic-queue/api/json", "application/json")
                .getWebResponse()
                .getContentAsString());
        assertTrue(ranking.has("configuration"), "a reader must receive the ranking payload");
    }

    @Test
    @DisplayName("the endpoint answers on an empty queue")
    void emptyQueueIsValid(JenkinsRule j) throws Exception {
        JSONObject root = getJson(j, "dynamic-queue/api/json");

        assertEquals(0, root.getInt("queueLength"));
        assertTrue(root.getJSONArray("items").isEmpty());
        assertTrue(root.getJSONArray("unscoredItems").isEmpty());
    }

    private static void schedule(JenkinsRule j, String name, String level) throws IOException {
        FreeStyleProject project = j.createFreeStyleProject(name);
        project.addProperty(new JobPriorityProperty(level, ""));
        project.scheduleBuild2(0);
    }
}
