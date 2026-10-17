"""
The values `BookRecord.enrichment_status` can hold.

They live here, not in `api_enricher`, because the store, the server and the
reports all need them and none of those should import the HTTP enrichment
module to find out what a status string means.
"""

VERIFIED = "verified"        # accepted by the gate; identity fields written
BORDERLINE = "borderline"    # descriptive fields only — the review queue
REJECTED = "rejected"        # candidates found, none good enough
UNMATCHED = "unmatched"      # no provider had this book
NO_EVIDENCE = "no_evidence"  # no ISBN, no usable title: never queried
DEFERRED = "deferred"        # provider errors; retried on the next run

#: Outcomes that mean "we do not know what this file is". A human can often
#: name these from the cover, but nothing is *wrong* with them to confirm.
UNIDENTIFIED = (REJECTED, UNMATCHED, NO_EVIDENCE)

ALL = (VERIFIED, BORDERLINE, REJECTED, UNMATCHED, NO_EVIDENCE, DEFERRED)
