package io.jenkins.plugins.queueoptimizer.metrics;

import edu.umd.cs.findbugs.annotations.CheckForNull;
import edu.umd.cs.findbugs.annotations.NonNull;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * One recorded scheduling or build event, ready to be posted to the backend.
 *
 * <p>Plain data with a hand-rolled JSON writer rather than a serialisation library, because the
 * plugin's dependency surface should stay as close to Jenkins core as possible and the shape here
 * is small and fixed.
 *
 * <p>Every event carries the numbers the backend needs to recompute a KPI from raw rows, never a
 * pre-aggregated figure. That is the same principle as report section 5.14: a metric that cannot
 * be recomputed from what was recorded is a metric nobody can defend in a viva.
 */
public final class MetricEvent {

    /** What happened. The backend switches on this. */
    public enum Kind {
        QUEUE_ENTERED,
        QUEUE_LEFT,
        BUILD_STARTED,
        BUILD_COMPLETED
    }

    private final Kind kind;
    private final long timestampMillis;
    private final Map<String, Object> fields = new LinkedHashMap<>();

    private MetricEvent(Kind kind, long timestampMillis) {
        this.kind = kind;
        this.timestampMillis = timestampMillis;
    }

    public static MetricEvent of(@NonNull Kind kind) {
        return new MetricEvent(kind, System.currentTimeMillis());
    }

    /** Adds a field, ignoring nulls so callers need not branch on optional data. */
    public MetricEvent with(@NonNull String key, @CheckForNull Object value) {
        if (value != null) {
            fields.put(key, value);
        }
        return this;
    }

    @NonNull
    public Kind getKind() {
        return kind;
    }

    public long getTimestampMillis() {
        return timestampMillis;
    }

    @NonNull
    public Map<String, Object> getFields() {
        return Map.copyOf(fields);
    }

    /** @return this event as a JSON object */
    @NonNull
    public String toJson() {
        StringBuilder json = new StringBuilder(128);
        json.append("{\"kind\":\"").append(kind.name()).append('"');
        json.append(",\"timestamp\":").append(timestampMillis);
        for (Map.Entry<String, Object> field : fields.entrySet()) {
            json.append(',').append(jsonEscape(field.getKey())).append(':').append(render(field.getValue()));
        }
        return json.append('}').toString();
    }

    private static String render(Object value) {
        if (value instanceof Number || value instanceof Boolean) {
            return String.valueOf(value);
        }
        return jsonEscape(String.valueOf(value));
    }

    /**
     * Escapes a string as a JSON string literal, quotes included.
     *
     * <p>Public and shared with {@code DynamicQueueApi}, which renders the same kind of small
     * fixed-shape JSON. Job names and blockage reasons reach both, and a job name may legally
     * contain a quote or a control character, so one escaper serves both rather than two that can
     * drift apart.
     */
    public static String jsonEscape(String raw) {
        StringBuilder out = new StringBuilder(raw.length() + 2).append('"');
        for (int i = 0; i < raw.length(); i++) {
            char c = raw.charAt(i);
            switch (c) {
                case '"' -> out.append("\\\"");
                case '\\' -> out.append("\\\\");
                case '\n' -> out.append("\\n");
                case '\r' -> out.append("\\r");
                case '\t' -> out.append("\\t");
                case '\b' -> out.append("\\b");
                case '\f' -> out.append("\\f");
                default -> {
                    if (c < 0x20) {
                        out.append(String.format("\\u%04x", (int) c));
                    } else {
                        out.append(c);
                    }
                }
            }
        }
        return out.append('"').toString();
    }

    @Override
    public String toString() {
        return toJson();
    }
}
