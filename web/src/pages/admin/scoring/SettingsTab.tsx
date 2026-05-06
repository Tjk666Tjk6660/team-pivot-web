import { ConfigTab } from "./ConfigTab";
import { WeightsTab } from "./WeightsTab";

/** Combined settings tab: config (toggle / visibility / model / timeout) +
 *  high-weight commenters list. Each piece is a self-contained card with
 *  its own data fetch — composing them here keeps the file focused while
 *  keeping the underlying components reusable (e.g. for future split). */
export function SettingsTab() {
  return (
    <div className="space-y-6">
      <ConfigTab />
      <WeightsTab />
    </div>
  );
}
