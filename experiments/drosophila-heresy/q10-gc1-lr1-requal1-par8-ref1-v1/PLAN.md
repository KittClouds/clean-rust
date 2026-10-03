# REQUAL1-PAR8-REF1: current-lineage PAR8 reference requalification

This engineering-only identity reruns the global coalition assembly for the
eight current REQUAL1 contexts from the fresh closure and current palette
inputs. It does not read the historical PAR8 execution as a result source,
does not import historical counts, and does not replay pairs or run behavior.

The runner uses the current live assembly implementation only after hashing
all imported source files and the fresh closure inputs. The result is a fresh
reference object for downstream current-lineage selectors. Historical PAR8
contract, plan, runner, and parent claims are comparison artifacts only.

The run fails closed on source/closure drift, duplicate context keys, palette
topology drift, illegal committed bytes, non-finite geometry, incomplete
assembly, or any write outside this identity.
