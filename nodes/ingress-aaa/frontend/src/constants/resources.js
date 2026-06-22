export const RESOURCE_TYPES = [
  { type: "object_storage", label: "File Storage", icon: "⬡", color: "#4a9eff" },
  { type: "database", label: "Database", icon: "⬢", color: "#a78bfa" },
  { type: "vm", label: "Virtual Machine", icon: "⬣", color: "#34d399" },
  { type: "cache", label: "Cache", icon: "⬤", color: "#fbbf24" },
];

export const RESOURCE_FIELDS = {
  object_storage: [
    {
      key: "bucket_suffix",
      label: "Storage Name",
      placeholder: "vd: project-files",
      required: true
    },
    {
      key: "versioning",
      label: "Keep File History",
      type: "select",
      options: ["Enabled", "Suspended"],
      defaultValue: "Enabled"
    },
    {
      key: "expiration_days",
      label: "Delete Current Objects After Days",
      placeholder: "365",
      defaultValue: "365"
    },
    {
      key: "noncurrent_expiration_days",
      label: "Delete Old Versions After Days",
      placeholder: "90",
      defaultValue: "90"
    },
    {
      key: "force_destroy",
      label: "Force Delete Non-empty Bucket",
      type: "select",
      options: ["false", "true"],
      defaultValue: "false"
    },
  ],

  database: [
    { key: "db_name", label: "Database Name", placeholder: "mydb", required: true },
    { key: "db_size", label: "Storage Size (GB)", placeholder: "10", defaultValue: "10" },
  ],

  vm: [
    { key: "vm_name", label: "Server Name", placeholder: "demo-vm", required: true },
    {
      key: "image_name",
      label: "Image",
      type: "select",
      options: ["Ubuntu-20.04"],
      defaultValue: "Ubuntu-20.04"
    },
    {
      key: "flavor_name",
      label: "Flavor",
      type: "select",
      options: ["m1.tiny", "m1.small", "m1.magnum-worker", "m1.magnum-master"],
      defaultValue: "m1.tiny"
    },
    {
      key: "network_name",
      label: "Network",
      type: "select",
      options: ["public1"],
      defaultValue: "public1"
    },
  ],

  cache: [
    { key: "cache_name", label: "Cache Name", placeholder: "app-cache", required: true },
    { key: "num_nodes", label: "Number of Nodes", placeholder: "1", defaultValue: "1" },
  ],
};
export const RESOURCE_LABELS = {
  object_storage: "File Storage",
  cache: "Cache",
  vm: "Virtual Machine",
  database: "Database",
};

export function getResourceLabel(resourceType) {
  return RESOURCE_LABELS[resourceType] || resourceType || "Resource";
}
