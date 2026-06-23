"use client";

import TransactionForm from "@/components/TransactionForm";
import PageHeader from "@/components/PageHeader";

/** Submit Transaction view (REQUIREMENTS §11.1). */
export default function SubmitPage() {
  return (
    <div className="grid">
      <PageHeader
        eyebrow="Operations"
        title="Submit Transaction"
        description="Each submission uses a unique idempotency key. Replaying the same key returns the original transaction without creating a duplicate."
      />
      <div className="card">
        <TransactionForm />
      </div>
    </div>
  );
}
