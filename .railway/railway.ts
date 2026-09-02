import {
  defineRailway,
  empty,
  postgres,
  preserve,
  project,
  redis,
  service,
  volume,
} from "railway/iac";

const region = "asia-southeast1-eqsg3a";

export default defineRailway(() => {
  const brainData = volume("gizmo-brain-data", { region, sizeMB: 1024 });

  // Railway's managed Postgres 18 image includes the vector extension.
  const db = postgres("postgres", { region });

  const cache = redis("redis", { region });

  const memobase = service("memobase", {
    // Deploy with `railway up`; GitHub App repository access is not configured.
    source: empty(),
    rootDirectory: "deploy/memobase",
    replicas: { [region]: 1 },
    healthcheck: "/api/v1/healthcheck",
    healthcheckTimeout: 120,
    env: {
      PORT: "8000",
      DATABASE_URL: db.env.DATABASE_URL,
      REDIS_URL: cache.env.REDIS_URL,
      ACCESS_TOKEN: preserve(),
      PROJECT_ID: "gizmo",
      LOG_FORMAT: "json",
      MEMOBASE_LLM_API_KEY: preserve(),
      MEMOBASE_INTERNAL_URL: "http://${{RAILWAY_PRIVATE_DOMAIN}}:8000",
    },
  });

  const brain = service("gizmo-brain", {
    source: empty(),
    replicas: { [region]: 1 },
    healthcheck: "/health",
    healthcheckTimeout: 30,
    env: {
      GEMINI_API_KEY: preserve(),
      GIZMO_DEVICE_TOKEN: preserve(),
      GIZMO_USER_ID: "gizmo-owner",
      GIZMO_DATA_DIR: "/data",
      MEMOBASE_URL: memobase.env.MEMOBASE_INTERNAL_URL,
      MEMOBASE_API_KEY: memobase.env.ACCESS_TOKEN,
    },
    volumeMounts: { "/data": brainData },
  });

  return project("gizmo", {
    resources: [db, cache, memobase, brain],
  });
});
