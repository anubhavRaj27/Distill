"""The user's field schema: proposing it, evolving it, versioning it, and querying it.

Named ``schema`` (singular) and meaning only "the user's field schema". There is
deliberately no ``schemas/`` package for request and response models, which is the usual
FastAPI convention, because that word already means something specific and central here.
See ``app/domain/__init__.py`` for the full convention.
"""
