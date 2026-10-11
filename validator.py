"""Offline Kubernetes schema checks and explicit, reviewable configuration advice."""
import re
from typing import Any

import yaml
from kubernetes_validate import validate, ValidationError, SchemaNotFoundError

MAX_BYTES = 512 * 1024
MAX_DOCUMENTS = 100
VERSIONS = ("1.32.0", "1.33.0", "1.34.0", "1.35.0", "1.36.0")
DEFAULT_VERSION = "1.34.0"


class InputError(ValueError):
    pass


class BoundedLoader(yaml.SafeLoader):
    """Reject aliases, duplicate keys, deep trees and excessive node counts."""
    def __init__(self, stream):
        super().__init__(stream)
        self.depth = 0
        self.nodes = 0

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise InputError("YAML aliases are not supported. Expand anchor references before validation.")
        self.nodes += 1
        self.depth += 1
        try:
            if self.nodes > 30000 or self.depth > 40:
                raise InputError("Manifest is too complex: use fewer nodes and at most 40 nesting levels.")
            return super().compose_node(parent, index)
        finally:
            self.depth -= 1

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise InputError("YAML mapping keys must be strings.")
            if key in result:
                raise InputError("Duplicate YAML key detected. Keep one value for each key.")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


BoundedLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, BoundedLoader.construct_mapping)


def finding(doc, code, severity, path, message, suggestion):
    return dict(document=doc, code=code, severity=severity, path=path, message=message, suggestion=suggestion)


def _pod(resource):
    kind = resource.get("kind")
    spec = resource.get("spec", {})
    if kind == "Pod":
        return spec, "spec", resource.get("metadata", {})
    if kind == "CronJob":
        template = spec.get("jobTemplate", {}).get("spec", {}).get("template", {})
        return template.get("spec", {}), "spec.jobTemplate.spec.template.spec", template.get("metadata", {})
    if kind in ("Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job", "ReplicationController"):
        template = spec.get("template", {})
        return template.get("spec", {}), "spec.template.spec", template.get("metadata", {})
    return None, "", {}


def _matches(selector, labels):
    if not isinstance(selector, dict) or not selector:
        return False
    if any(labels.get(k) != v for k, v in selector.get("matchLabels", {}).items()):
        return False
    for item in selector.get("matchExpressions", []):
        key, op, values = item.get("key"), item.get("operator"), item.get("values", [])
        if op == "In" and (key not in labels or labels[key] not in values): return False
        if op == "NotIn" and key in labels and labels[key] in values: return False
        if op == "Exists" and key not in labels: return False
        if op == "DoesNotExist" and key in labels: return False
    return bool(selector.get("matchLabels") or selector.get("matchExpressions"))


def _rules(resource, doc):
    issues = []
    pod, path, metadata = _pod(resource)
    if pod is None:
        return issues
    labels = metadata.get("labels", {})
    if resource["kind"] in ("Deployment", "StatefulSet", "DaemonSet", "ReplicaSet"):
        if not _matches(resource["spec"].get("selector"), labels):
            issues.append(finding(doc, "SELECTOR_MISMATCH", "error", "spec.selector",
                                  "The workload selector does not match its Pod template labels.",
                                  "Align matchLabels/matchExpressions with spec.template.metadata.labels."))
    pod_security = pod.get("securityContext", {})
    for group in ("containers", "initContainers"):
        for i, container in enumerate(pod.get(group, [])):
            base = f"{path}.{group}[{i}]"
            image = container.get("image", "")
            if isinstance(image, str):
                if "@sha256:" not in image and (":" not in image.rsplit("/", 1)[-1] or image.endswith(":latest")):
                    issues.append(finding(doc, "FLOATING_IMAGE", "warning", base + ".image",
                                          "The image reference can change between deployments.",
                                          "Use a version tag or, for immutable references, a verified image digest."))
            resources = container.get("resources", {})
            if any(not resources.get(section, {}).get(key) for section in ("requests", "limits") for key in ("cpu", "memory")):
                issues.append(finding(doc, "RESOURCE_BUDGET", "warning", base + ".resources",
                                      "CPU/memory requests or limits are missing.",
                                      "Set resource values based on observed usage; do not copy arbitrary limits."))
            security = container.get("securityContext", {})
            if security.get("privileged") is True:
                issues.append(finding(doc, "PRIVILEGED_CONTAINER", "warning", base + ".securityContext.privileged",
                                      "The container requests privileged mode.", "Disable privileged mode unless it is required and reviewed."))
            if security.get("runAsNonRoot", pod_security.get("runAsNonRoot")) is not True:
                issues.append(finding(doc, "NON_ROOT", "warning", base + ".securityContext",
                                      "Non-root execution is not explicitly required.",
                                      "Use an image that supports a non-root user, then set runAsNonRoot: true."))
            if group == "containers" and "readinessProbe" not in container:
                issues.append(finding(doc, "READINESS_PROBE", "warning", base,
                                      "No readiness probe is configured.", "Add an application-appropriate readiness probe before routing traffic."))
    return issues


def analyze(text: str, version: str = DEFAULT_VERSION) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise InputError("Paste a non-empty Kubernetes YAML manifest.")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise InputError("Manifest exceeds the 512 KiB limit.")
    if version not in VERSIONS:
        raise InputError("Choose one of the supported Kubernetes schema versions.")
    resources = []
    loader = BoundedLoader(text)
    try:
        while loader.check_data():
            resource = loader.get_data()
            if resource is None:
                continue
            if isinstance(resource, dict) and resource.get("kind") == "List":
                if not isinstance(resource.get("items"), list):
                    raise InputError("A Kubernetes List must contain an items array.")
                resources.extend(resource["items"])
            else:
                resources.append(resource)
            if len(resources) > MAX_DOCUMENTS:
                raise InputError("Validate at most 100 resources in one request.")
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        # Never echo YAML snippets or values: manifests can contain credentials.
        raise InputError("Invalid YAML" + location + ". Check indentation, quoting and separators.") from None
    finally:
        loader.dispose()
    if not resources:
        raise InputError("No Kubernetes resources were found.")
    issues = []
    seen = set()
    covered = 0
    for doc, resource in enumerate(resources, 1):
        if not isinstance(resource, dict):
            issues.append(finding(doc, "RESOURCE_OBJECT", "error", "", "A resource must be a YAML object.", "Provide apiVersion, kind, metadata and the resource fields."))
            continue
        if any(not isinstance(resource.get(key), str) or not resource[key] for key in ("apiVersion", "kind")):
            issues.append(finding(doc, "RESOURCE_IDENTITY", "error", "", "apiVersion or kind is missing or is not a string.", "Set a supported API version and resource kind."))
            continue
        metadata = resource.get("metadata", {})
        if not isinstance(metadata, dict) or not (metadata.get("name") or metadata.get("generateName")):
            issues.append(finding(doc, "RESOURCE_NAME", "error", "metadata", "Resource name is missing.", "Set metadata.name, or generateName when creating a generated-name resource."))
        if isinstance(metadata, dict) and isinstance(metadata.get("name"), str):
            group = resource["apiVersion"].split("/")[0] if "/" in resource["apiVersion"] else "core"
            identity = (group, resource["kind"], str(metadata.get("namespace", "default")), metadata["name"])
            if identity in seen:
                issues.append(finding(doc, "DUPLICATE_RESOURCE", "error", "metadata", "This resource appears more than once in the input.", "Keep one definition for each group/kind/namespace/name."))
            seen.add(identity)
        try:
            validate(resource, desired_version=version, strict=True)
            covered += 1
        except SchemaNotFoundError:
            issues.append(finding(doc, "SCHEMA_UNAVAILABLE", "warning", "apiVersion/kind", "No matching built-in schema was found for this API version and kind.", "Check API availability for the selected version. Custom resources need their CRD schema and cluster validation."))
            continue
        except ValidationError as exc:
            covered += 1
            path = ".".join(str(part) for part in exc.path)
            issues.append(finding(doc, "SCHEMA_ERROR", "error", path, f"The resource violates its Kubernetes schema ({exc.validator}).", "Check the field at this path against the selected Kubernetes version; correct its type, required fields or unsupported keys."))
            continue
        issues.extend(_rules(resource, doc))
    errors = sum(item["severity"] == "error" for item in issues)
    warnings = sum(item["severity"] == "warning" for item in issues)
    complete = covered == len(resources)
    return {"schema_version": version, "resource_count": len(resources), "schema_coverage_complete": complete,
            "outcome": "invalid" if errors else ("incomplete" if not complete else "valid"),
            "error_count": errors, "warning_count": warnings, "findings": issues,
            "scope": "Offline schema and selected configuration checks. No cluster admission, image availability, runtime or deployment verification."}
