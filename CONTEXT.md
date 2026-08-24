# Echora domain language

## User

A person identified by an immutable email address from the configured OIDC provider. The email is the username. The user may change their display name without changing identity.

## Administrator

A user allowed to manage OIDC provisioning and user access. The environment-named bootstrap administrator must sign in first and cannot remove their own access.

## OIDC provisioning policy

The deployment-wide rule that controls whether a new OIDC identity may create a user automatically. Automatic provisioning starts enabled. Administrators can disable it without affecting existing users.

## OIDC approval

An email address explicitly allowed to create an Echora user on its next matching OIDC sign-in, even when automatic provisioning is disabled. Approval is consumed when the user is created.

## Blocked user

A user denied access by an administrator. Blocking deletes every active Echora session immediately but keeps the user's library links, settings, and analysis data.

## Track

A media object ingested from a music server. A track has stable byte identity and keeps its shared metadata and embeddings even when it belongs to several libraries or a recording group.

## Library

A collection of tracks discovered through one music source. Libraries determine which shared tracks a user can browse, map, and play.

## User library

A user's association with a library they added. It establishes the source through which tracks can become visible.

## User track link

A user's current link to a shared track through one library. Synchronization creates links for songs present in that user's live catalog and removes links for songs no longer present. Removing a link does not delete shared metadata or representations.

## Recording group

A non-destructive set of tracks believed to contain the same recording. Membership records evidence and confidence. Grouping never deletes or replaces tracks.

## Representation

A model-specific vector for a track. Echora keeps semantic, acoustic, and lyrics representations separate and records the model revision that produced each result.

## Model snapshot

An immutable set of model files downloaded from a pinned repository revision. Deployments cache snapshots on persistent storage before analysis starts, then load them with network downloads disabled.

## Lyrics document

The available textual lyrics for a track, including source, language, synchronization data, and provenance. Missing lyrics and instrumental tracks are distinct states.

## Lyrics representation

A model-specific vector derived from a lyrics document. It describes lyrical language and themes, not the sound of the recording.

## Similarity blend

A weighted comparison that combines semantic, acoustic, and optional lyrics similarities at query time. It is not a stored embedding. Missing lyrics never cause Echora to silently change the requested weights.

## Community snapshot

A reproducible partition of a fixed track corpus in one representation or similarity blend. Community identifiers and ordinals belong to that snapshot and need not survive another snapshot.

## Community

A connected group discovered from the track-similarity graph. A community is a latent grouping, not an objective genre or a single exclusive concept. Audio, lyrics, and blended community snapshots remain distinguishable.

## Community membership

A track's strength of association with a community. One membership is primary for map partitioning, while secondary memberships describe overlap.

## Connection

A bounded, full-dimensional similarity relationship between two tracks. Projection distance does not define a connection.

## Bridge track

A track with strong connections or memberships across more than one community.

## Artist facet

A coherent part of an artist's catalogue represented by a component of the artist profile.

## Taste profile

A user-specific summary built from observed listening activity.

## Taste facet

One coherent mode within a taste profile. A taste profile can contain several weighted facets.

## Sonic journey

An ordered playlist of real tracks that follows intermediate targets between two tracks in a chosen representation or similarity blend.

## Curation

A user-owned, fully managed Navidrome playlist generated from a saved recipe. A curation can refresh every six hours or only when requested.

## Curation type

The source of evidence that defines a curation recipe. Language curations use positive and negative text. Like / not like curations use explicit track examples. Time-of-day curations use listens within a recurring local-time period.

## Curation recipe

The durable curation type, its positive and negative evidence, familiarity mix, ranking mode, and adjustable track limit used to refresh a curation.

## Familiarity mix

A per-curation target split between relevant tracks played during its lookback window and relevant discovery tracks not played during that window. Recent play frequency boosts familiar candidates. The final membership is shuffled before publishing.

## Listening-history connection

A user-owned link to an external listening-history provider. It is separate from the sync server connection and uses the user's timezone when assigning listens to recurring clock periods.

## Time-of-day curation

A curation whose positive examples are tracks listened to within a recurring local-time period during its lookback window. Its discovery tracks are similar to those examples but were not played anywhere in the lookback window.

## Curation revision

One generated membership and ordering of a curation. A revision records its recipe and evidence so the result can be explained and reproduced.

## Lyrical concept

An overlapping association between a lyrics representation and a textual theme such as grief, place, relationships, or storytelling. A lyrical concept does not claim that the audio sounds like the concept.

## Recording fingerprint

An acoustic signature used as evidence that tracks contain the same recording. It is not the track's canonical identity.
