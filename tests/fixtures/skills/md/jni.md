---
id: jni-native-handle-lifecycle
triggers: jni-handle
provenance: md-fixture:jni
---
Pair every nativeCreate* with a nativeRelease*; guard a null handle; match the JNI signature to the Java
native declaration.
