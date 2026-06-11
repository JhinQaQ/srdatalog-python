I’m trying to understand the distinction between required_indices and canonical_index in srdatalog-python HIR.

I have some code in [../examples/09_ir_translation_walkthrough.py](../examples/09_ir_translation_walkthrough.py).

My current understanding is:

required_indices[Rel]  = all physical index layouts needed to read/join Rel   within or across strata. 
canonical_index[Rel]  = one chosen primary layout used to maintain Rel's NEW / DELTA / FULL    versions: insert, dedup, compute delta, merge.

But I’m still confused about why the canonical index is chosen the way it is, and how non-canonical required indexes are maintained.

For example, in simple transitive closure:

```
Path(x, y) :- Edge(x, y). 
Path(x, z) :- Path(x, y), Edge(y, z).
```

The recursive rule reads:

```
Path(x, y)
```

and joins on y, which is column 1 of Path, so it needs:

```
Path[1,0]
```

So I think:

```
required_indices["Path"] = [[1,0]] canonical_index["Path"] = [1,0]
```

That case makes sense because there is only one useful Path index.

But in path composition:

```
Path(x, z) :- Path(x, y), Path(y, z).
```

the same relation is read in two different ways:

```
Path(x, y)  joins on y = column 1 -> needs Path[1,0] Path(y, z)  joins on y = column 0 -> needs Path[0,1]
```

So HIR has:

```
required_indices["Path"] = [[0,1], [1,0]] canonical_index["Path"] = [0,1]
```

My questions are:

1. What is the exact definition of canonical_index?   Is my understanding "the primary full-arity layout used for NEW/DELTA/FULL   maintenance" right? 
2. If required_indices has multiple layouts, do we maintain all of them for the relation’s relevant versions, or do we maintain only the canonical_index and rebuild the other required layouts when needed? ( Otherwise i think it's kind of overlap?)
3. Why does the current implementation choose [0,1] as canonical in the   Path(x,y), Path(y,z) example?   
   Is it just because [0,1] is the first qualifying full-arity index after  sorting, or is there a deeper reason (cost-model)? 
4. Is canonical_index semantically meaningful, or purely a physical  implementation choice? 
5. If canonical_index were changed from [0,1] to [1,0] in the path  composition example, should the query result stay the same and only  performance/codegen shape change?
