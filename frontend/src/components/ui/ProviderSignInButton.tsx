import type { ButtonHTMLAttributes } from "react";
import googleLogo from "../../assets/auth/google.svg";
import appleLogo from "../../assets/auth/apple.svg";
import { Button } from "./Button";
import "./ProviderSignInButton.css";

type ProviderSignInButtonProps = Pick<ButtonHTMLAttributes<HTMLButtonElement>, "onClick"> & {
  provider: "google" | "apple";
  intent: "signin" | "signup";
  busy: boolean;
};

export function ProviderSignInButton({ provider, intent, busy, onClick }: ProviderSignInButtonProps): React.JSX.Element {
  const name = provider === "google" ? "Google" : "Apple";
  const label = `${intent === "signup" ? "Sign up" : "Sign in"} with ${name}`;

  return (
    <Button
      variant="secondary"
      className={`provider-signin-button provider-signin-button--${provider}`}
      disabled={busy}
      aria-busy={busy}
      aria-label={label}
      onClick={onClick}
      leftIcon={<img src={provider === "google" ? googleLogo : appleLogo} width={provider === "google" ? 20 : 31} height={provider === "google" ? 20 : 44} alt="" aria-hidden="true" draggable={false} />}
    >
      {busy ? "Please wait…" : label}
    </Button>
  );
}
