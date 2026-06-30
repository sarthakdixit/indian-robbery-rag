import { Turnstile } from "@marsidev/react-turnstile";
import { env } from "@/config/env";

type TurnstileWidgetProps = {
  onVerify: (token: string) => void;
  onError?: (() => void) | undefined;
  onExpire?: (() => void) | undefined;
};

/**
 * Wraps Cloudflare Turnstile. In local dev, the test site key
 * (1x00000000000000000000AA) always passes, so this is effectively
 * a no-op. In cloud, it presents the actual invisible CAPTCHA.
 *
 * The token returned by `onVerify` is submitted with the query and
 * verified server-side. Tokens are single-use; the widget refreshes
 * itself after each verification.
 */
export function TurnstileWidget({ onVerify, onError, onExpire }: TurnstileWidgetProps) {
  return (
    <Turnstile
      siteKey={env.VITE_TURNSTILE_SITE_KEY}
      onSuccess={onVerify}
      onError={onError}
      onExpire={onExpire}
      options={{
        theme: "auto",
        size: "flexible",
        appearance: "interaction-only",
      }}
    />
  );
}
