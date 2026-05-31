import axios from "axios";

const API_URL = import.meta.env.VITE_BACKEND_URL;

export const api = axios.create({
  baseURL: API_URL,
  withCredentials: true,
});

let interceptorsReady = false;

export function setupApiInterceptors(onUnauthorized) {
  if (interceptorsReady) return;
  interceptorsReady = true;

  api.interceptors.response.use(
    (response) => response,
    async (error) => {
      const config = error.config;
      const status = error.response?.status;
      const url = config?.url || "";

      if (
        !config ||
        config._authRetry ||
        status !== 401 ||
        url.includes("/auth/login") ||
        url.includes("/auth/register") ||
        url.includes("/auth/refresh") ||
        url.includes("/auth/logout")
      ) {
        return Promise.reject(error);
      }

      config._authRetry = true;

      try {
        await api.post("/auth/refresh");
        return api(config);
      } catch {
        onUnauthorized?.();
        return Promise.reject(error);
      }
    }
  );
}
