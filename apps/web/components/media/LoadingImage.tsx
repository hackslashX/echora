"use client";

import Image from "next/image";
import { useState } from "react";
import styles from "./LoadingImage.module.css";

export default function LoadingImage({ src, alt = "", sizes, priority = false, className = "" }: { src: string; alt?: string; sizes: string; priority?: boolean; className?: string }) {
  const [loaded, setLoaded] = useState(false);
  return <span className={`${styles.frame} ${className}`}>
    {!loaded && <i className={styles.spinner} aria-label="Loading artwork" />}
    <Image unoptimized fill sizes={sizes} priority={priority} src={src} alt={alt} className={loaded ? styles.loaded : styles.loading} onLoad={() => setLoaded(true)} />
  </span>;
}
