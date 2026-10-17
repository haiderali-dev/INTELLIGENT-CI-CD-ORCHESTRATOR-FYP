import { cva, type VariantProps } from "class-variance-authority";

/**
 * Buttons (DESIGN.md sections 2 and 7). The primary action is Ink, a near-black button in light
 * mode and a near-white one in dark, because there is no brand colour. Secondary buttons are
 * outlined in Graphite. 2px corners, and at least 44px tall under 768 px, where they are touched.
 * A button that cannot act yet stays focusable (aria-disabled), so its label is still read out.
 */
export const button = cva(
  [
    "inline-flex items-center justify-center gap-2 rounded-control px-4 text-base font-semibold",
    "h-10 max-md:h-11 aria-disabled:cursor-not-allowed aria-disabled:opacity-60",
  ],
  {
    variants: {
      variant: {
        primary: "bg-ink text-panel",
        secondary: "border border-graphite bg-panel text-ink hover:bg-ground",
      },
    },
    defaultVariants: { variant: "secondary" },
  },
);

export type ButtonVariant = NonNullable<VariantProps<typeof button>["variant"]>;
