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
      options: ["Enabled", "Disabled"],
      defaultValue: "Enabled"
    },
  ],

  database: [
    { key: "db_name", label: "Database Name", placeholder: "mydb", required: true },
    { key: "db_size", label: "Storage Size (GB)", placeholder: "10", defaultValue: "10" },
  ],

  vm: [
    { key: "vm_name", label: "Server Name", placeholder: "app-server", required: true },
    {
      key: "flavor_id",
      label: "Server Size",
      type: "select",
      options: ["Small", "Medium", "Large"],
      defaultValue: "Small"
    },
    {
      key: "image",
      label: "Operating System",
      type: "select",
      options: ["Ubuntu 22.04", "CentOS 9"],
      defaultValue: "Ubuntu 22.04"
    },
  ],

  cache: [
    { key: "cache_name", label: "Cache Name", placeholder: "app-cache", required: true },
    { key: "num_nodes", label: "Number of Nodes", placeholder: "1", defaultValue: "1" },
  ],
};