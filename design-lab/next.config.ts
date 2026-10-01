import type { NextConfig } from "next";
const config: NextConfig = { devIndicators: false, turbopack: { root: process.cwd() + "/.." } };
export default config;
