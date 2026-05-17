/**
 * React hook providing the banner state + onMismatch callback for
 * `ContractMismatchBanner`. Pair with `BriefClient.onContractMismatch`.
 */
import { useCallback, useState } from "react";

import type { ContractMismatchEvent } from "../api/briefClient";
import type { ContractMismatchBannerState } from "./ContractMismatchBanner";

export function useContractMismatchState() {
  const [state, setState] = useState<ContractMismatchBannerState>({
    last: null,
    count: 0,
  });

  const onMismatch = useCallback((event: ContractMismatchEvent) => {
    setState((prev) => ({ last: event, count: prev.count + 1 }));
  }, []);

  const reset = useCallback(
    () => setState({ last: null, count: 0 }),
    [],
  );

  return { state, onMismatch, reset };
}
