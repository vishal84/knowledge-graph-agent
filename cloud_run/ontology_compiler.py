import logging
from typing import Optional, List, Set, Any

import rdflib
from rdflib.namespace import RDF, RDFS, OWL, SKOS

# Configure module-level logger for use in larger repos or notebooks
logger = logging.getLogger(__name__)

class OntologyCompiler:
    """
    A reusable module for parsing a TTL ontology file and compiling it into a
    structured Markdown summary. Optimized for LLM Agent context windows.
    Agnostic to namespaces and handles deep transitive graph inheritance.
    """
    def __init__(self, ttl_file_path: Optional[str] = None):
        """
        Initializes the compiler. Optionally loads an ontology file immediately.
        """
        self.g = rdflib.Graph()
        if ttl_file_path:
            self.load(ttl_file_path)

    def load(self, ttl_file_path: str) -> None:
        """
        Loads and parses the TTL ontology file into the internal rdflib Graph.
        """
        try:
            self.g.parse(ttl_file_path, format="turtle")
            logger.info(f"Successfully loaded ontology from '{ttl_file_path}'")
        except Exception as e:
            logger.error(f"Error parsing ontology: {e}")
            raise ValueError(f"Failed to parse ontology file: {e}")

    @staticmethod
    def _get_local_name(uri: Any) -> str:
        """Extracts the local name from a URI."""
        if not uri:
            return "UNKNOWN"
        uri_str = str(uri)
        return uri_str.split('#')[-1] if '#' in uri_str else uri_str.split('/')[-1]

    def _get_directive(self, subject: Any, directive_name: str) -> List[Any]:
        """
        Namespace-Agnostic extraction. Finds properties like 'edgeFilter'
        regardless of what the base URI / Prefix is. Protects against drift.
        """
        results = []
        for p, o in self.g.predicate_objects(subject):
            if self._get_local_name(p) == directive_name:
                results.append(o)
        return results

    def _get_synonyms(self, subject: Any) -> str:
        """Retrieves SKOS alternative labels as a formatted string."""
        synonyms = [str(obj) for obj in self.g.objects(subject, SKOS.altLabel)]
        return f"  - Synonyms: {', '.join(synonyms)}\n" if synonyms else ""

    def compile_summary(self) -> str:
        """
        Generates the formatted Markdown summary from the loaded ontology graph.
        Handles nodes, edges, properties, and deep inheritance.
        """
        if len(self.g) == 0:
            return "Error: Ontology graph is empty or not loaded."

        summary = "### ONTOLOGY: GRAPH NODES\n"

        # 1. Compile Classes (Nodes)
        for cls in self.g.subjects(RDF.type, OWL.Class):
            db_table = self._get_local_name(cls)

            # Re-introduced human-readable labels for semantic matching
            label = self.g.value(cls, RDFS.label)
            display_name = f"'{label}' (Spanner Node: {db_table})" if label else db_table

            summary += f"- Node: {display_name}\n"
            summary += self._get_synonyms(cls)

        # 2. Compile Object Properties (Edges)
        summary += "\n### ONTOLOGY: GRAPH EDGES (RELATIONSHIPS)\n"
        for prop in self.g.subjects(RDF.type, OWL.ObjectProperty):
            # Resolve Domains and Ranges (checking parents recursively if missing)
            domains = list(self.g.objects(prop, RDFS.domain))
            ranges = list(self.g.objects(prop, RDFS.range))

            if not domains or not ranges:
                # Deep graph inheritance via transitive_objects (crawls all ancestors)
                for parent in self.g.transitive_objects(prop, RDFS.subPropertyOf):
                    if parent == prop: continue
                    if not domains:
                        domains.extend(self.g.objects(parent, RDFS.domain))
                    if not ranges:
                        ranges.extend(self.g.objects(parent, RDFS.range))
                    if domains and ranges:
                        break

            domain_str = ", ".join([self._get_local_name(d) for d in domains]) or "Any"
            range_str = ", ".join([self._get_local_name(r) for r in ranges]) or "Any"

            summary += f"- Edge: [{self._get_local_name(prop)}] (Direction: {domain_str} -> {range_str})\n"
            summary += self._get_synonyms(prop)

            # FIX: Bulletproof Bidirectional Inverse Detection
            is_declared_forward = list(self.g.objects(prop, OWL.inverseOf))
            is_declared_reverse = list(self.g.subjects(OWL.inverseOf, prop))

            inverses = is_declared_forward + is_declared_reverse
            is_physical_reverse = bool(is_declared_reverse and not is_declared_forward)

            # Agnostic Directive Extraction (with Inverse Inheritance)
            edge_labels = self._get_directive(prop, "gqlEdgeLabel")
            if not edge_labels and inverses:
                for inv in inverses:
                    inv_labels = self._get_directive(inv, "gqlEdgeLabel")
                    if inv_labels:
                        edge_labels = inv_labels
                        break

            edge_filters = self._get_directive(prop, "edgeFilter")
            if not edge_filters and inverses:
                for inv in inverses:
                    inv_filters = self._get_directive(inv, "edgeFilter")
                    if inv_filters:
                        edge_filters = inv_filters
                        break

            if edge_labels:
                summary += f"  - Spanner Edge Label: {edge_labels[0]}\n"

            if edge_filters:
                summary += f"  - GQL Filter: {edge_filters[0]}\n"

            edge_lbl = edge_labels[0] if edge_labels else '?'
            filter_str = f" {{{edge_filters[0]}}}" if edge_filters else ""

            # If this edge is a logical reverse, warn the LLM to write the GQL backwards
            if is_physical_reverse:
                summary += f"  - GRAPH DIRECTION WARNING: The physical Spanner edge points backwards. You MUST write this traversal as: <-[{edge_lbl}{filter_str}]-\n"

            # Explicit GQL instructions for the LLM
            if inverses:
                inv_names = [self._get_local_name(inv) for inv in inverses]
                if is_physical_reverse:
                    summary += f"  - Inverse Relationships: {', '.join(inv_names)} (To query this, use the FORWARD GQL edge direction: -[{edge_lbl}{filter_str}]->)\n"
                else:
                    summary += f"  - Inverse Relationships: {', '.join(inv_names)} (To query this, reverse the GQL edge direction to: <-[{edge_lbl}{filter_str}]-)\n"

        # 3. Compile Datatype Properties (Columns/Attributes)
        summary += "\n### ONTOLOGY: NODE ATTRIBUTES (SEARCHABLE COLUMNS)\n"
        for prop in self.g.subjects(RDF.type, OWL.DatatypeProperty):
            prop_name = self._get_local_name(prop)

            domains = list(self.g.objects(prop, RDFS.domain))
            if not domains:
                # Deep inheritance for column domains
                for parent in self.g.transitive_objects(prop, RDFS.subPropertyOf):
                    if parent == prop: continue
                    domains.extend(self.g.objects(parent, RDFS.domain))
                    if domains: break

            # Agnostic Extraction of AppliesToEdge
            base_applies_to_edges = self._get_directive(prop, "appliesToEdge")
            expanded_edges = set(base_applies_to_edges)

            # FIX: Deep Transitive Graph Inheritance. If column applies to Edge A, it applies to all children of Edge A.
            for edge in base_applies_to_edges:
                sub_edges = list(self.g.transitive_subjects(RDFS.subPropertyOf, edge))
                expanded_edges.update(sub_edges)

            location_parts = []
            if domains:
                domain_names = [self._get_local_name(d) for d in domains]
                location_parts.append(f"Node(s): {', '.join(domain_names)}")
            if expanded_edges:
                edge_names = [self._get_local_name(e) for e in expanded_edges]
                location_parts.append(f"Edge(s): {', '.join(edge_names)}")

            location = " | ".join(location_parts) if location_parts else "UNKNOWN"

            summary += f"- Attribute: [{prop_name}] (Applies to {location})\n"

            comment = self.g.value(prop, RDFS.comment)
            if comment:
                summary += f"  - Context: {comment}\n"

            summary += self._get_synonyms(prop)

            examples = [str(obj) for obj in self.g.objects(prop, SKOS.example)]
            if examples:
                # Replaced single quotes with backticks and explicitly instructed LLM
                quoted_examples = [f"`{ex}`" for ex in examples]
                summary += f"  - Valid DB Examples (Use exact string matching): {', '.join(quoted_examples)}\n"

            strategies = self._get_directive(prop, "searchStrategy")
            if strategies:
                strat_val = str(strategies[0])
                strat_desc = "(Use exact string/B-Tree match)" if "EXACT" in strat_val else "(Use vector similarity search)"
                summary += f"  - Search Strategy: {strat_val} {strat_desc}\n"

        return summary


# ==============================================================================
# LEGACY WRAPPER FUNCTION (For backward compatibility with existing code)
# ==============================================================================
def compile_ontology_for_agent(ttl_file_path: str) -> str:
    """
    Parses the TTL ontology file and compiles it into a structured Markdown
    summary. Wrapper for the OntologyCompiler class to ensure backward compatibility.
    """
    try:
        compiler = OntologyCompiler(ttl_file_path)
        return compiler.compile_summary()
    except Exception as e:
        return f"Error parsing ontology: {e}"


# # --- Example Usage ---
# if __name__ == "__main__":
#     # Example showing how you might import and use it in a notebook or script
#     logging.basicConfig(level=logging.INFO)

#     # Notice: We no longer need to pass namespace_uri! It is fully decoupled.
#     # Approach 1: Object-Oriented (Recommended)
#     # my_compiler = OntologyCompiler('ontology_file.ttl')
#     # print(my_compiler.compile_summary())

#     # Approach 2: Functional (Legacy)
#     compiled_prompt = compile_ontology_for_agent('ontology_file.ttl')
#     print(compiled_prompt)