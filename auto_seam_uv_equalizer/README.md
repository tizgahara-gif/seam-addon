# Auto Seam UV Equalizer v0.8.x

Blender 5.1向けに、ZBrush / GoZから来たメッシュのシーム作成、UV展開、配置、対称転送、検証を段階的に行うアドオンです。新しいサイドバーは複合的な Quick Actions ではなく、現在の工程と作用範囲が分かる5つのセクションで構成されています。

## Installation

`auto_seam_uv_equalizer.zip` を **Edit > Preferences > Add-ons > Install...** からインストールし、3D Viewの **N > Auto UV** を開きます。GitHubのソースアーカイブではなく、リリース用zipを使用してください。

## Five-stage panel

### 1. Seam

**Classic** は角度、マテリアル境界、開放境界、非多様体の規則でシームを生成します。**Chart-Based** は Organic / Cloth、Hard Surface、Cylinder / Strip、Manual Assisted のプリセットとUV品質評価を使います。Analyze Seamsは診断のみ、Generate Seamsは適用です。

Analyze / Generateの作用範囲は選択メッシュオブジェクトです。Selected BoundaryとMirror Seamなどの **Assist — Active Object** はアクティブオブジェクトだけに作用します。ForceとProtectはEdit Modeのアクティブオブジェクトで現在選択している辺だけが対象です。**Clear All Tags** はモードや辺選択に関係なくActive ObjectのForce / Protectタグをすべて消去します。Mirror Seamは共通のMesh Symmetry Axis / Toleranceを使い、Selected Side → OppositeだけはEdit Modeの選択辺を必要とします。Selected BoundaryのInclude Open BoundariesはUIで確認できます。詳細パラメータとCharacter Front AxisはAdvanced内にあります。

### 2. Unwrap

**Unwrap Selected Faces** はEdit Modeの選択面だけを変更します。**Unwrap Selected Objects** は選択メッシュオブジェクト全体を既存シームでUV展開します。任意の **Selected Objects Post-Unwrap**（Average Island Scale / Straighten Circular Strip Islands）はUnwrap Selected Objectsにだけ作用し、Unwrap Selected Facesには作用せず、既定ではOFFです。**Unwrap Margin** はこのUV展開だけに使用され、Pack Marginとは独立しています。UVがなくCreate UV If Missingが有効な場合は、UV展開時に新規作成します。Ring / StripはEdit ModeではActive Object / Selected Faces、Object ModeではSelected Mesh Objects / Whole Objectsが対象で、現在のScopeをUIに表示します。

### 3. Layout

**Weighted Island Layout** はScope、Target UV Region（FULL / LEFT_HALF / RIGHT_HALF）、Density Influence、Scale Mode、Texture Size、Padding Pixelsを使用します。Scopeの **Selected UV Islands** はEdit Modeの面選択をseedとし、選択面を1枚以上含む既存UVアイランド全体を処理します。内部ID `SELECTED_FACES` は既存`.blend`互換のため維持しますが、面の一部分だけを移動しません。

#### Shared Weighted Atlas

**Per-Object Weighted Layout** は各オブジェクトがTarget Regionを個別に使用します。**Shared Weighted Atlas** は選択された全オブジェクトのアイランドを一つのpoolに集め、global median polygon densityでimportanceを計算し、既存の回転なしWeighted MaxRectsで一つの共有アトラスへ配置します。対して **Atlas Pack** は現在のアイランド縮尺を基本として一つのアトラスへパックします。Shared Weighted AtlasはUV面積をグローバルに再配分し、Atlas PackやAverage Islands Scaleを自動実行しません。FULL / LEFT_HALF / RIGHT_HALFとSelected UV Islandsをサポートします。

linked objectはProcess Shared Mesh Data Onceが有効ならMesh datablockごとに決定的な代表を一つ処理します。無効な状態で同じMesh datablockが複数対象に含まれる場合は、独立したUV配置が不可能なため処理を中止します。全対象を検証してpending UVを生成してから一括commitし、失敗時は全対象の元UVへrollbackします。

**Pack Islands** は選択メッシュオブジェクトを個別にパックします。Pack Margin、Rotation、Margin Methodに加え、Pack AdvancedでShape Method、Lock Pinned Islands、Pin Method、Merge Overlapping、Pack Targetを確認できます。**Atlas Pack Selected Objects** は選択オブジェクトを一つの共有アトラスへパックします。Weighted Layout / Packは全対象に使用可能なUVが必要で、欠落時はUIとoperatorの双方で実行せず、silent skipしません。Process Shared Mesh Data Onceはパネル上部の共通Processing設定です。有効ならlinked duplicateは各工程を通して固有Mesh datablockごとに1回だけ処理され、複数選択時はUIに選択数と固有数を表示します。AtlasのAverage Island ScaleはWeightedのAllocate by Importanceが作った相対スケールを上書きする可能性があるため、該当する現在設定の組合せでは警告します（実行は禁止しません）。

#### Distortion-Guided Seam Candidates

Chart-BasedのAdvancedにある **Distortion-Guided Candidates** は、current temporary unwrapのface distortionからlocalized hotspotを見つけ、先に試行する候補を最大2枠確保します。quality評価と同じcut-state UV snapshot cacheを共有するため追加unwrapは行いません。歪みguidanceは候補の試行順だけを決め、シームを強制せず、distortion scoreをfinal benefitへ加算しません。最終採用は従来どおりtemporary Blender unwrap後に実測したUV quality improvement、seam cost、sparsity、Protect、Mirror Pair規則で決まります。OFFでは従来のprofessional candidate選択へ戻ります。

#### Follow Clean Edge Loops

Chart-BasedのAdvancedにある **Follow Clean Edge Loops** は、シーム候補全体がcleanなtopological edge loop上にある場合、quad face内のopposite edge continuityを双方向へ追跡し、自然な終端まで完成させた候補も試行します。元の短い候補は保持されます。Loop completionはシームを強制せず、完成候補もtemporary Blender unwrapによる実測UV品質改善と既存のseam cost、sparsity、Protect、Mirror Pair規則を満たす必要があります。

追跡はmesh boundary、existing seam、current chart cut、protected edge、pole、triangle、n-gon、chart boundary、または曖昧なtopologyで停止します。閉じたring loopは安全なtrial candidateとして扱います。袖、円筒状の衣服、脚、pipeなどquad主体のtubular meshで特に有効です。OFFにするとloop completion expansionを行わず、従来のcandidate poolへ戻ります。

Distortion guidance refines anchored charts. Anchorless closed charts still bootstrap using the existing geodesic path.

### 4. Symmetry

**Mesh Symmetry Axis** と **Mesh Symmetry Tolerance** はProfessional Garment Prior、Mirror Seam、Validate Symmetry、Standard UV Transfer、Exact Texture-Xのジオメトリ対応付けで共通です。Direction / Source Sideは用途別のままです。対称処理のTargetは常にActive Objectで、Scopeはそのオブジェクト内のSelected FacesまたはWhole Meshを意味します。Selected Facesの場合はEdit Modeが必須です。

Exact Texture-Xの **Texture Source Side** は3D Mesh Source Sideとは独立しています。転送元UVは指定したLeft HalfまたはRight Halfと0–1領域内に完全に収まる必要があります。Weighted TargetとTexture Sourceが一致しない場合、パネルが実行前に警告します。「Layout settings match Exact Texture-X.」は設定値の一致だけを示し、UVや対称対応の検証成功を保証しません。本当の検証はOperator実行時に行います。

#### Mirrored UV Island Synchronization

1. Enter Edit Mode.
2. Select faces belonging to exactly one source UV island. A partial face selection is expanded internally to that complete island without changing the mesh selection.
3. Run **Synchronize Mirrored UV Island**.
4. The mirrored counterpart receives the same mesh seam ON/OFF states and the exact same UV coordinates.
5. The two UV islands overlap exactly.

**Standard UV Transfer** is the existing general symmetry UV-transfer workflow. **Synchronize Mirrored UV Island** instead treats one selected UV island as authoritative and overwrites its mirrored counterpart. It performs `Udest = Usrc` and `Vdest = Vsrc`; it does not flip, rotate, pack, or re-unwrap UVs and does not call Weighted Layout or Atlas Pack.

This operation requires a complete one-to-one symmetric face, edge, vertex, and loop topology mapping using the shared **Mesh Symmetry Axis** and **Mesh Symmetry Tolerance**. It never guesses a missing correspondence. Centerline/cross-plane islands, ambiguous matches, multiple selected islands, and incomplete topology are cancelled without modifying seams or UVs. Target seams and UV coordinates are snapshotted and rolled back together if committing fails. UV pin and UV/mesh selection states are preserved.

#### Flip Selected UV Islands

**Flip Selected UV Islands** horizontally flips each selected UV island around
its own bounding-box center. It is Edit Mode-only and affects only the active
object. Selecting any face expands the operation internally to that complete UV
island, while mesh and UV selection remain unchanged. Each island uses its own
pivot, so its position is preserved. Seams are not modified and packing is not
performed. UVs outside the 0–1 range and zero-width islands are supported.

### 5. Validation

**Check Overlap** は問題面を非破壊的に選択し、マテリアルを変更しません。Check Across ObjectsがONなら共有atlasを想定して異なる選択オブジェクト間も比較し、OFFなら各オブジェクト内部だけを検査します。結果は **Clear Overlap Selection** で解除できます。**Run UV Quality Check** はstretch、flipped face、zero-area face、UV triangle面積合計などを検査してLast Quality Reportへ表示し、flipped / zero-area面を結果として選択します。

## Recommended workflow

```text
ZBrush
↓
GoZ
↓
Seam
↓
Unwrap
↓
Weighted Layout / Pack
↓
Symmetry
↓
Validation
↓
External Texture Paint
```

通常はChart-Based + Organic / ClothからGenerate Seams、Unwrap Selected Objects、Weighted FULL、Pack、Validationへ進みます。

Exact Texture-Xを使う場合は次の順序にします。

```text
Weighted LEFT_HALF または RIGHT_HALF
↓
Exact Texture-X（同じTexture Source Side）
```

**この2工程の間やExact Texture-X後にPackを実行しないでください。** Packは厳密な `U_source + U_destination = 1` の関係を壊す可能性があります。

## Compatibility

旧 **Auto Seam + Unwrap** と **Auto Unwrap + Pack** operator IDは`.blend`やスクリプト互換用backendとして残りますが、通常パネルには表示されません。アルゴリズム（Classic、Chart-Based、Professional Prior、Ring / Strip、Weighted BBox packing、Symmetry pairing、Exact Texture-X、Overlap detection）は変更していません。

## Known limitations

- Chart-Based候補は実測UV品質に基づくため、意図した見えない位置を常に選ぶとは限りません。
- Ring / Stripは対応する連結quad topologyが必要です。
- Exact Texture-Xは事前に片側halfへ収まったUVを必要とします。
- Atlas Packはmaterial統合、texture bake、画像統合を行いません。
- 非一様Object Scaleや複雑なhero assetは手動確認が必要です。
