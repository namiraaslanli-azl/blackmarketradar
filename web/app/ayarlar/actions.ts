"use server";

import { revalidatePath } from "next/cache";
import { api } from "@/lib/api";

export async function addKeyword(form: FormData) {
  const term = String(form.get("term") ?? "").trim();
  if (term.length < 2) return;
  await api("/api/settings/keywords", {
    method: "POST",
    body: JSON.stringify({ term, kind: String(form.get("kind") ?? "generic"), lang: String(form.get("lang") ?? "") || null }),
  });
  revalidatePath("/ayarlar");
}

export async function deleteKeyword(form: FormData) {
  await api(`/api/settings/keywords/${Number(form.get("id"))}`, { method: "DELETE" });
  revalidatePath("/ayarlar");
}

export async function addWhitelist(form: FormData) {
  const value = String(form.get("value") ?? "").trim();
  if (value.length < 2) return;
  await api("/api/settings/whitelist", {
    method: "POST",
    body: JSON.stringify({ kind: String(form.get("kind")), value, owner: String(form.get("owner")), note: null }),
  });
  revalidatePath("/ayarlar");
}

export async function deleteWhitelist(form: FormData) {
  await api(`/api/settings/whitelist/${Number(form.get("id"))}`, { method: "DELETE" });
  revalidatePath("/ayarlar");
}

export async function addTarget(form: FormData) {
  const value = String(form.get("value") ?? "").trim();
  if (value.length < 2) return;
  await api("/api/settings/targets", {
    method: "POST",
    body: JSON.stringify({ kind: String(form.get("kind")), value, note: String(form.get("note") ?? "") || null }),
  });
  revalidatePath("/ayarlar");
}

export async function deleteTarget(form: FormData) {
  await api(`/api/settings/targets/${Number(form.get("id"))}`, { method: "DELETE" });
  revalidatePath("/ayarlar");
}
