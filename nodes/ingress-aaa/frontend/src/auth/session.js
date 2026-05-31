import { api } from "../api/client";

export async function checkSession() {
  const res = await api.get("/me");
  return res.data;
}

export async function login(credentials) {
  await api.post("/auth/login", credentials);
}

export async function logout() {
  try {
    await api.post("/auth/logout");
  } catch {
    // Clear local UI even if the server call fails.
  }
}
