import json
import argparse
import sys
import os

def normalize_tfsec(data):
    normalized = []
    for item in data.get("results", []):
        # Bỏ qua các rule đã pass (nếu có)
        if item.get("status", 0) == 0 and item.get("passed", False):
            continue
            
        normalized.append({
            "scanner": "tfsec",
            "rule_id": item.get("rule_id", "UNKNOWN"),
            "severity": item.get("severity", "UNKNOWN").upper(),
            "resource": item.get("resource", "UNKNOWN"),
            "description": item.get("description", ""),
            "file_path": item.get("location", {}).get("filename", "UNKNOWN"),
            "line": item.get("location", {}).get("start_line", 0)
        })
    return normalized

def normalize_checkov(data):
    normalized = []
    # Checkov thường chia thành passed_checks, failed_checks, skipped_checks
    failed_checks = data.get("results", {}).get("failed_checks", [])
    
    for item in failed_checks:
        # Checkov bản open-source đôi khi trả về severity = null, ta set mặc định hoặc lấy từ ID
        severity = item.get("severity") 
        if not severity:
            severity = "UNKNOWN"
            
        line_range = item.get("file_line_range", [0])
        start_line = line_range[0] if line_range else 0

        normalized.append({
            "scanner": "checkov",
            "rule_id": item.get("check_id", "UNKNOWN"),
            "severity": severity.upper() if severity else "UNKNOWN",
            "resource": item.get("resource", "UNKNOWN"),
            "description": item.get("check_name", ""),
            "file_path": item.get("file_path", "UNKNOWN"),
            "line": start_line
        })
    return normalized

def normalize_trivy(data):
    normalized = []
    for result in data.get("Results", []):
        file_path = result.get("Target", "UNKNOWN")
        for item in result.get("Misconfigurations", []):
            if item.get("Status") == "FAIL":
                cause = item.get("CauseMetadata", {})
                normalized.append({
                    "scanner": "trivy",
                    "rule_id": item.get("ID", "UNKNOWN"),
                    "severity": item.get("Severity", "UNKNOWN").upper(),
                    "resource": cause.get("Resource", "UNKNOWN"),
                    "description": item.get("Title", ""),
                    "file_path": file_path,
                    "line": cause.get("StartLine", 0)
                })
    return normalized

def main():
    parser = argparse.ArgumentParser(description="Normalize IaC Scanner Outputs")
    parser.add_argument("--tool", required=True, choices=["tfsec", "checkov", "trivy"], help="The scanner tool used")
    parser.add_argument("--input", required=True, help="Input JSON file path")
    parser.add_argument("--output", default="normalized-results.json", help="Output JSON file path")
    
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input file '{args.input}' not found.")
        sys.exit(1)

    with open(args.input, 'r') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print("Error: Invalid JSON format in input file.")
            sys.exit(1)

    normalized_data = []
    if args.tool == "tfsec":
        normalized_data = normalize_tfsec(data)
    elif args.tool == "checkov":
        normalized_data = normalize_checkov(data)
    elif args.tool == "trivy":
        normalized_data = normalize_trivy(data)

    # Đọc dữ liệu cũ nếu file output đã tồn tại để gộp (Merge) kết quả của nhiều tool
    final_output = []
    if os.path.exists(args.output):
        with open(args.output, 'r') as f:
            try:
                final_output = json.load(f)
            except json.JSONDecodeError:
                pass 
    
    final_output.extend(normalized_data)

    with open(args.output, 'w') as f:
        json.dump(final_output, f, indent=2)
        
    print(f"✅ Successfully normalized {args.tool} results. Total vulnerabilities in {args.output}: {len(final_output)}")

if __name__ == "__main__":
    main()