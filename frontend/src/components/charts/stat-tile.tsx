import { Card, CardContent } from "@/components/ui/card";

/**
 * A headline number: label (sentence case, no colon), the value in proportional
 * figures, and one line of context. The number is the chart; there is no plot.
 */
export function StatTile({
  label,
  value,
  context,
}: {
  label: string;
  value: React.ReactNode;
  context?: React.ReactNode;
}) {
  return (
    <Card size="sm">
      <CardContent>
        <dl>
          <dt className="text-sm text-muted-foreground">{label}</dt>
          <dd className="mt-1 text-3xl font-semibold tracking-tight">{value}</dd>
          {context ? <dd className="mt-1 text-xs text-muted-foreground">{context}</dd> : null}
        </dl>
      </CardContent>
    </Card>
  );
}
