import { useCallback, useEffect, useState } from "react";
import { usePlaidLink } from "react-plaid-link";
import { api } from "../api";

export default function PlaidLinkButton({
  onLinked,
  onError,
}: {
  onLinked: () => void;
  onError?: (msg: string) => void;
}) {
  const [token, setToken] = useState<string | null>(null);
  const [tokenError, setTokenError] = useState<string | null>(null);

  useEffect(() => {
    api.createLinkToken()
      .then((t) => { setToken(t); setTokenError(null); })
      .catch(() => {
        setToken(null);
        const msg = "Could not start bank connection. Please try again.";
        setTokenError(msg);
        onError?.(msg);
      });
  }, [onError]);

  const onSuccess = useCallback(
    async (public_token: string) => {
      try {
        await api.exchangePublicToken(public_token);
        onLinked();
      } catch {
        const msg = "Failed to link your bank account. Please try again.";
        setTokenError(msg);
        onError?.(msg);
      }
    },
    [onLinked, onError],
  );

  const { open, ready } = usePlaidLink({ token: token ?? "", onSuccess });

  return (
    <div className="inline-flex flex-col gap-1">
      <button
        onClick={() => open()}
        disabled={!ready || !token}
        className="px-4 py-2 rounded-lg bg-emerald-600 text-white text-sm font-medium disabled:opacity-50"
      >
        + Connect a bank
      </button>
      {!onError && tokenError && (
        <div className="text-xs text-red-600">{tokenError}</div>
      )}
    </div>
  );
}
