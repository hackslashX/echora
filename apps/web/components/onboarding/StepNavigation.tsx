import styles from "./StepNavigation.module.css";

const names = ["Connect", "Select", "Process"];

export default function StepNavigation({ step, navigate }: { step: number; navigate: (step: number) => void }) {
  return <nav className={styles.nav} aria-label="Setup progress">{names.map((name, index) => <button key={name} className={index === step ? styles.active : index < step ? styles.complete : styles.pending} disabled={index > step} onClick={() => index <= step && navigate(index)}>{index < step ? <b aria-label="Completed" /> : index === step ? <i /> : null}{name.toUpperCase()}</button>)}</nav>;
}
