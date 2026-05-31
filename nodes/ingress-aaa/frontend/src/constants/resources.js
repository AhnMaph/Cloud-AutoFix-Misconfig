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
    { key: "vm_name", label: "Server Name", placeholder: "demo-vm", required: true },
    {
      key: "image_name",
      label: "Image",
      type: "select",
      options: ["cirros"],
      defaultValue: "cirros"
    },
    {
      key: "flavor_name",
      label: "Flavor",
      type: "select",
      options: ["m1.tiny"],
      defaultValue: "m1.tiny"
    },
    {
      key: "network_name",
      label: "Network",
      type: "select",
      options: ["public-net"],
      defaultValue: "public-net"
    },
  ],

  cache: [
    { key: "cache_name", label: "Cache Name", placeholder: "app-cache", required: true },
    { key: "num_nodes", label: "Number of Nodes", placeholder: "1", defaultValue: "1" },
  ],
};