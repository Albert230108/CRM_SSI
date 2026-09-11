// A payment row is "paid" once its Status holds anything other than "not paid" -
// in practice, the date it was actually paid. Mirrors the backend's
// payment_plan.is_paid so the editor's confirm dialogs and a regenerated plan
// agree on which rows are untouchable.
export function isPaymentPaid(status: string | undefined): boolean {
  const cleaned = (status ?? '').trim()
  return cleaned.length > 0 && cleaned.toLowerCase() !== 'not paid'
}
