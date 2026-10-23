"use server";

import { revalidatePath } from "next/cache";
import { api } from "@/lib/api";

export async function toggleCollector(form: FormData) {
  await api(`/api/collectors/${encodeURIComponent(String(form.get("name")))}`, {
    method: "PUT",
    body: JSON.stringify({ enabled: form.get("enabled") === "true" }),
  });
  revalidatePath("/kollektorlar");
}

export async function runCollector(form: FormData) {
  await api(`/api/collectors/${encodeURIComponent(String(form.get("name")))}/run`, { method: "POST" });
  revalidatePath("/kollektorlar");
}
