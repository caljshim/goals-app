import Goals from "./Goals";

/** Recurring behavior workspace. It deliberately reuses the goal editor/cards so
 * progress, history, scheduling, and dashboard behavior stay consistent. */
export default function Routines() {
  return <Goals mode="routines" />;
}
