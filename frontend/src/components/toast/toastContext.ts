import { createContext, useContext } from "react";

/** Shows a short message that confirms what the user just did, such as "Run started". */
export type ShowToast = (message: string) => void;

export const ToastContext = createContext<ShowToast | null>(null);

export function useToast(): ShowToast {
  const show = useContext(ToastContext);
  if (!show) {
    throw new Error("useToast needs a <ToastProvider> above it");
  }
  return show;
}
