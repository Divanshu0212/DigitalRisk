"use client";

import TransactionForm from "@/components/TransactionForm";

/** Submit Transaction view (REQUIREMENTS §11.1). */
export default function SubmitPage() {
  return (
    <div className="grid">
      <h1>Submit Transaction</h1>
      <p className="muted">
        Each submission uses a unique idempotency key. Replaying the same key returns the original
        transaction without creating a duplicate.
      </p>
      <div className="card">
        <TransactionForm />
      </div>
    </div>
  );
}
