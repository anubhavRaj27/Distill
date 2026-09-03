"""Pure domain types. No input or output, no database, no network.

NAMING CONVENTION FOR THE WHOLE SERVER (see backend-plan.md review finding 8.10)
--------------------------------------------------------------------------------
There is deliberately no ``app/schemas/`` package, even though that is the common FastAPI
convention for request and response models. In this project the word "schema" already means
something specific and central: **the user's field schema**, the thing the product infers,
evolves, and versions. Using the same word for two different ideas in one tree is a
permanent cost to every future reader.

So:

* ``app/schema/``   the user's field schema feature: proposal, drift, versioning, views.
* ``app/domain/``   types shared across features, such as the ones in this package.
* request and response models are declared at the top of the router that owns them, because
  a model used by exactly one route belongs beside that route.
"""
