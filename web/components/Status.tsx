import { STATUS_LABEL } from "@/lib/labels";

export default function Status({ s }: { s: string }) {
  return <span className={`st st-${s}`}>{STATUS_LABEL[s] ?? s}</span>;
}
