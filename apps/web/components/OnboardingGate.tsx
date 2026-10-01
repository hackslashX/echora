"use client";

import { useEffect } from "react";
import { Spinner } from "./ui/spinner";

export default function OnboardingGate() {
  useEffect(() => {
    fetch("/analysis/auth/me").then(response => {
      if (response.status === 401) { window.location.replace("/login"); return null; }
      if (!response.ok) throw new Error("Could not read user preferences");
      return response.json();
    }).then(user => {
      if (user) window.location.replace(user.onboarding_complete ? "/home" : "/connect");
    }).catch(() => window.location.replace("/login"));
  }, []);

  return <main className="route-loading"><div className="flex flex-col items-center gap-4"><span>ECHORA</span><Spinner className="size-5 text-primary" label="Loading Echora" /></div></main>;
}
