"use client";

import { useEffect } from "react";
import { PlaybackPreferences, readPlaybackPreferences } from "../player/playbackPreferences";
import { compactLayoutEvent, readCompactLayoutPreference } from "./layoutPreference";

const playbackRate = (speed: PlaybackPreferences["animationSpeed"]) => speed === "slow" ? .65 : speed === "fast" ? 1.45 : 1;

export default function MotionPreferences() {
  useEffect(() => {
    let rate = playbackRate(readPlaybackPreferences().animationSpeed);
    const apply = () => document.getAnimations().forEach(animation => { animation.playbackRate = rate; });
    const receive = (event: Event) => {
      rate = playbackRate((event as CustomEvent<PlaybackPreferences>).detail.animationSpeed);
      apply();
    };
    const started = () => requestAnimationFrame(apply);
    window.addEventListener("echora:playback-preferences", receive);
    document.addEventListener("animationstart", started, true);
    document.addEventListener("transitionrun", started, true);
    apply();
    return () => {
      window.removeEventListener("echora:playback-preferences", receive);
      document.removeEventListener("animationstart", started, true);
      document.removeEventListener("transitionrun", started, true);
    };
  }, []);

  useEffect(() => {
    const style = document.createElement("style");
    style.dataset.echoraCompactRules = "true";
    document.head.appendChild(style);

    const compactCondition = /max-(?:width:\s*1199px|height:\s*719px)/;
    const prefixRules = (rules: CSSRuleList) => {
      const output: string[] = [];
      for (const rule of Array.from(rules)) {
        if (!(rule instanceof CSSStyleRule)) continue;
        const selectors = rule.selectorText.split(",").map(selector => `:where(body.echora-force-compact) ${selector.trim()}`).join(",");
        output.push(`${selectors}{${rule.style.cssText}}`);
      }
      return output.join("\n");
    };
    const rebuild = () => {
      const output: string[] = [];
      const landscape = window.matchMedia("(orientation: landscape)").matches;
      for (const sheet of Array.from(document.styleSheets)) {
        if (sheet.ownerNode === style) continue;
        try {
          for (const rule of Array.from(sheet.cssRules)) {
            if (!(rule instanceof CSSMediaRule) || !compactCondition.test(rule.conditionText)) continue;
            const wantsLandscape = rule.conditionText.includes("orientation: landscape");
            const wantsPortrait = rule.conditionText.includes("orientation: portrait");
            if ((wantsLandscape && !landscape) || (wantsPortrait && landscape)) continue;
            output.push(prefixRules(rule.cssRules));
          }
        } catch { /* Ignore browser and extension stylesheets without CSSOM access. */ }
      }
      style.textContent = output.join("\n");
    };
    const apply = (enabled: boolean) => {
      document.body.classList.toggle("echora-force-compact", enabled);
      if (enabled) requestAnimationFrame(rebuild);
    };
    const receive = (event: Event) => apply(Boolean((event as CustomEvent<boolean>).detail));
    const changed = () => { if (document.body.classList.contains("echora-force-compact")) requestAnimationFrame(rebuild); };
    const observer = new MutationObserver(changed);
    observer.observe(document.head, { childList: true, subtree: true });
    window.addEventListener(compactLayoutEvent, receive);
    window.addEventListener("resize", changed);
    apply(readCompactLayoutPreference());
    const settled = window.setTimeout(changed, 250);
    return () => {
      window.clearTimeout(settled);
      observer.disconnect();
      window.removeEventListener(compactLayoutEvent, receive);
      window.removeEventListener("resize", changed);
      document.body.classList.remove("echora-force-compact");
      style.remove();
    };
  }, []);
  return null;
}
