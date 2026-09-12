"use client";

import { useState } from "react";
import styles from "./MobilePane.module.css";

/** Tab order determines the entering pane's direction, including skipped tabs. */
export function useMobilePane<Key extends string>(initial: Key, order: readonly Key[]) {
  const [state, setState] = useState({ active: initial, backward: false });
  function select(next: Key) {
    setState(previous => {
      if (next === previous.active) return previous;
      return { active: next, backward: order.indexOf(next) < order.indexOf(previous.active) };
    });
  }
  const transition = `${styles.active} ${state.backward ? styles.backward : ""}`;
  return [state.active, select, transition] as const;
}
