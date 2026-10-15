import { button } from "@/components/button";

/** 4.7.4: "the question plus up to four answer buttons; typing still works". */
export const MAX_ANSWERS = 4;

/**
 * A question the assistant needs answered before it can go on. The message's words are the
 * question, so the page renders this in place of them. The buttons send an answer; the composer
 * stays open for any other.
 */
export function Clarification({
  question,
  options,
  onAnswer,
  disabled = false,
}: {
  question: string;
  options: readonly string[];
  onAnswer: (answer: string) => void;
  disabled?: boolean;
}) {
  const answers = options.slice(0, MAX_ANSWERS);
  return (
    <div className="flex flex-col gap-2">
      <p>{question}</p>
      {answers.length > 0 ? (
        <div role="group" aria-label="Answers" className="flex flex-wrap gap-2">
          {answers.map((answer) => (
            <button
              key={answer}
              type="button"
              aria-disabled={disabled}
              onClick={() => {
                if (!disabled) {
                  onAnswer(answer);
                }
              }}
              className={button()}
            >
              {answer}
            </button>
          ))}
        </div>
      ) : null}
      <p className="text-sm text-graphite">
        {answers.length > 0 ? "Or type a different answer below." : "Type your answer below."}
      </p>
    </div>
  );
}
