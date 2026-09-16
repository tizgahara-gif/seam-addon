# Auto Seam UV Equalizer v0.8.x

Blender 5.1向けに、ZBrush / GoZから来たメッシュのシーム作成、UV展開、配置、対称転送、検証を段階的に行うアドオンです。新しいサイドバーは複合的な Quick Actions ではなく、現在の工程と作用範囲が分かる5つのセクションで構成されています。

## Installation

`auto_seam_uv_equalizer.zip` を **Edit > Preferences > Add-ons > Install...** からインストールし、3D Viewの **N > Auto UV** を開きます。GitHubのソースアーカイブではなく、リリース用zipを使用してください。

## Five-stage panel

### 1. Seam

**Classic** は角度、マテリアル境界、開放境界、非多様体の規則でシームを生成します。**Chart-Based** は Organic / Cloth、Hard Surface、Cylinder / Strip、Manual Assisted のプリセットとUV品質評価を使います。Analyze Seamsは診断のみ、Generate Seamsは適用です。

Analyze / Generateの作用範囲は選択メッシュオブジェクトです。Selected BoundaryとMirror Seamなどの **Assist — Active Object** はアクティブオブジェクトだけに作用します。ForceとProtectはEdit Modeのアクティブオブジェクトで現在選択している辺だけが対象です。**Clear All Tags** はモードや辺選択に関係なくActive ObjectのForce / Protectタグをすべて消去します。Mirror Seamは共通のMesh Symmetry Axis / Toleranceを使い、Selected Side → OppositeだけはEdit Modeの選択辺を必要とします。Selected BoundaryのInclude Open BoundariesはUIで確認できます。詳細パラメータとCharacter Front AxisはAdvanced内にあります。

### 2. Unwrap

**Unwrap Selected UV Islands** は、Edit Modeで選択した面をseedとして、その面を1枚以上含む**現在のActive UV Map上**のUVアイランド全体をアンラップします。この処理は **UV Map Name** を参照せず、Active UV Mapを切り替えず、UVマップも新規作成しません。Active UV Mapがない場合は、Create UV If Missingが有効でも副作用なくキャンセルします。未選択UVアイランドのUV座標は維持され、処理後は元のFace selection（頂点・辺・面のコンポーネント選択とMesh Select Modeを含む）へ復元されます。選択seedがFinished Islandに属する場合、そのアイランドはアンラップ対象外です。Finishedと編集可能なアイランドが混在する場合は編集可能なアイランドだけを処理し、すべてFinishedの場合は処理をキャンセルしてSelectionとModeを復元します。

**Unwrap Selected Objects** は選択メッシュオブジェクト全体を既存シームで、設定された **UV Map Name** へUV展開します。**Create UV If Missing** が有効なら、その名前のUVマップを作成できます。同じNamed UV設定は **Ring / Strip Unwrap**、**Atlas PackのUV Source = Named**、および該当するAuto / legacy unwrap workflowでも使用します。Atlasの **UV Source = Active** は各オブジェクトのActive UV Mapだけを使用し、Named設定を使用しません。任意の **Selected Objects Post-Unwrap**（Average Island Scale / Straighten Circular Strip Islands）はUnwrap Selected Objectsにだけ作用し、Unwrap Selected UV Islandsには作用せず、既定ではOFFです。**Unwrap Margin** はこのUV展開だけに使用され、Pack Marginとは独立しています。Ring / StripはEdit ModeではActive Object / Selected Faces、Object ModeではSelected Mesh Objects / Whole Objectsが対象で、現在のScopeをUIに表示します。

UV targetはoperatorごとに分離されています。Active-map workflowは **Unwrap Selected UV Islands、Weighted Island Layout、Pack Islands、Symmetry、Validation** です（各機能固有のScope規則は後述）。Named-map workflowでは上記のUV Map Name / Create UV If Missingを使用します。パネルのUnwrap AdvancedとAtlasのNamed設定は同じpropertyを表示するため、一方の変更は他方にも反映されます。

### 3. Layout

#### UV保護

日本語UIでは、保護機能の名称を次のように統一しています（括弧内は英語UI名です）。

| 英語UI名 | 日本語UI名 |
|---|---|
| UV Protection | UV保護 |
| Finished | 完成済み |
| Layout Lock | レイアウト固定 |
| Pack Selected Into Free Space | 選択UVアイランドを空き領域へ配置 |

**完成済み**

UVアイランドを完成済みとして設定すると、自動シーム、アンラップ、レイアウトなどの自動処理から保護されます。現在のシーム状態とUV座標は維持されます。

**レイアウト固定**

レイアウト固定されたUVアイランドは、Weighted LayoutやShared Weighted Atlas実行時にも現在の位置・回転・スケールを維持します。シーム生成やアンラップは保護しません。完成済みアイランドはRing / Strip Unwrapを含むUV座標を書き換える自動処理とシーム変更から保護されます。

| 機能 | シーム保護 | アンラップ保護 | 位置 | 回転 | スケール |
|---|---|---|---|---|---|
| 完成済み | ○ | ○ | ○ | ○ | ○ |
| レイアウト固定 | × | × | ○ | ○ | ○ |

**Weighted Island Layout** はScope、Target UV Region（FULL / LEFT_HALF / RIGHT_HALF）、Density Influence、Scale Mode、Paddingを使用します。テクスチャ解像度はWeighted LayoutのUV面積配分には影響しません。ピクセル単位で余白を指定する場合のみ、UV空間への換算に使用します。Paddingの **Relative UV** は解像度非依存のUV空間マージンを直接指定し、**Pixels** は選択したTexture Resolutionでピクセル余白を換算します。Scopeの **Selected UV Islands** はEdit Modeの面選択をseedとし、選択面を1枚以上含む既存UVアイランド全体を処理します。内部ID `SELECTED_FACES` は既存`.blend`互換のため維持しますが、面の一部分だけを移動しません。

**Allow 90° Island Rotation**（**90°アイランド回転を許可**）を有効にすると、Weighted MaxRects packerは配置効率が向上する場合に個々のUVアイランドを90°回転できます。回転はアイランドの重要度、UV面積配分、相対スケールを変更しません。布目、ヘアフローなどUV方向を維持する必要がある場合は無効にしてください。この設定は既存結果との互換性を保つため既定で無効で、Per-Object Weighted LayoutとShared Weighted Atlasの両方に適用されます。

When **Allow 90° Island Rotation** is enabled, the weighted MaxRects packer may rotate individual UV islands by 90 degrees when this improves placement. Rotation does not change island importance, UV area allocation, or scale. Disable this option when UV orientation must be preserved. It is off by default and is shared by Per-Object Weighted Layout and Shared Weighted Atlas.

Texture resolution does not affect weighted UV-area allocation. It is only required when padding is specified in pixels. **Relative UV** supplies a resolution-independent UV-space margin; **Pixels** converts the pixel margin using the selected texture resolution. Weighted Island Layout and Shared Weighted Atlas use the same resolved UV-space padding.

#### Shared Weighted Atlas

**Per-Object Weighted Layout** は各オブジェクトがTarget Regionを個別に使用します。**Shared Weighted Atlas** は選択された全オブジェクトのアイランドを一つのpoolに集め、global median polygon densityでimportanceを計算し、同じWeighted MaxRectsで一つの共有アトラスへ配置します。Allow 90° Island Rotationも両機能で共有されます。対して **Atlas Pack** は現在のアイランド縮尺を基本として一つのアトラスへパックします。Shared Weighted AtlasはUV面積をグローバルに再配分し、Atlas PackやAverage Islands Scaleを自動実行しません。FULL / LEFT_HALF / RIGHT_HALFとSelected UV Islandsをサポートします。Selected UV Islands scopeでは、未選択アイランド（通常・完成済み・レイアウト固定のすべて）を現在位置のObstacleとして維持します。この規則はPer-ObjectとShared Weighted Atlasで共通です。

linked objectはProcess Shared Mesh Data Onceが有効ならMesh datablockごとに決定的な代表を一つ処理します。無効な状態で同じMesh datablockが複数対象に含まれる場合は、独立したUV配置が不可能なため処理を中止します。全対象を検証してpending UVを生成してから一括commitし、失敗時は全対象の元UVへrollbackします。

**Pack Islands** は選択メッシュオブジェクトを個別にパックします。Pack Margin、Rotation、Margin Methodに加え、Pack AdvancedでShape Method、Lock Pinned Islands、Pin Method、Merge Overlapping、Pack Targetを確認でき、これらはすべてBlender標準Pack Islandsへ渡されます。UV Protectionが1アイランドでも有効な場合、Standard Pack Islandsは保護を維持できないため実行前に停止します（値がすべて0の保護Attributeは有効な保護とは扱いません）。**Atlas Pack Selected Objects** は選択オブジェクトを一つの共有アトラスへパックしますが、選択対象にUV Protectionがあれば全体を実行前に停止します。その場合はProtection-awareな **Shared Weighted Atlas** を使用してください。Weighted Layout / Packは全対象に使用可能なUVが必要で、欠落時はUIとoperatorの双方で実行せず、silent skipしません。Process Shared Mesh Data Onceはパネル上部の共通Processing設定です。有効ならlinked duplicateは各工程を通して固有Mesh datablockごとに1回だけ処理され、複数選択時はUIに選択数と固有数を表示します。AtlasのAverage Island ScaleはWeightedのAllocate by Importanceが作った相対スケールを上書きする可能性があるため、該当する現在設定の組合せでは警告します（実行は禁止しません）。

#### Distortion-Guided Seam Candidates

Chart-BasedのAdvancedにある **Distortion-Guided Candidates** は、current temporary unwrapのface distortionからlocalized hotspotを見つけ、先に試行する候補を最大2枠確保します。quality評価と同じcut-state UV snapshot cacheを共有するため追加unwrapは行いません。歪みguidanceは候補の試行順だけを決め、シームを強制せず、distortion scoreをfinal benefitへ加算しません。最終採用は従来どおりtemporary Blender unwrap後に実測したUV quality improvement、seam cost、sparsity、Protect、Mirror Pair規則で決まります。OFFでは従来のprofessional candidate選択へ戻ります。

#### Follow Clean Edge Loops

Chart-BasedのAdvancedにある **Follow Clean Edge Loops** は、シーム候補全体がcleanなtopological edge loop上にある場合、quad face内のopposite edge continuityを双方向へ追跡し、自然な終端まで完成させた候補も試行します。元の短い候補は保持されます。Loop completionはシームを強制せず、完成候補もtemporary Blender unwrapによる実測UV品質改善と既存のseam cost、sparsity、Protect、Mirror Pair規則を満たす必要があります。

追跡はmesh boundary、existing seam、current chart cut、protected edge、pole、triangle、n-gon、chart boundary、または曖昧なtopologyで停止します。閉じたring loopは安全なtrial candidateとして扱います。袖、円筒状の衣服、脚、pipeなどquad主体のtubular meshで特に有効です。OFFにするとloop completion expansionを行わず、従来のcandidate poolへ戻ります。

Distortion guidance refines anchored charts. Anchorless closed charts still bootstrap using the existing geodesic path.

### 4. Symmetry

**Mesh Symmetry Axis** と **Mesh Symmetry Tolerance** はProfessional Garment Prior、Mirror Seam、Validate Symmetry、Standard UV Transfer、Exact Texture-Xのジオメトリ対応付けで共通です。Direction / Source Sideは用途別のままです。対称処理のTargetは常にActive Objectで、Scopeはそのオブジェクト内のSelected FacesまたはWhole Meshを意味します。Selected Facesの場合はEdit Modeが必須です。

Exact Texture-Xの **Texture Source Side** は3D Mesh Source Sideとは独立しています。転送元UVは指定したLeft HalfまたはRight Halfと0–1領域内に完全に収まる必要があります。Weighted TargetとTexture Sourceが一致しない場合、パネルが実行前に警告します。「Layout settings match Exact Texture-X.」は設定値の一致だけを示し、UVや対称対応の検証成功を保証しません。本当の検証はOperator実行時に行います。

Source側のWeighted Layoutでは90°回転を使用できます。その後、Exact Texture-Xは完成済みSource UV layoutを反対側へ厳密にミラー転送します。Exact Texture-X後に左右を個別に再パックしないでください。

90° rotation may be used while laying out the source side. Exact Texture-X then mirrors the resulting source UV layout. Do not repack either side independently after Exact Texture-X.

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

**Check Overlap** は問題面を非破壊的に選択し、マテリアルを変更しません。Check Across ObjectsがONなら共有atlasを想定して異なる選択オブジェクト間も比較し、OFFなら各オブジェクト内部だけを検査します。結果は **Clear Overlap Selection** で解除できます。**Run UV Quality Check** はstretch、flipped face、zero-area face、UV triangle面積合計などを検査してLast Quality Reportへ表示し、flipped / zero-area / Stretch Warning Threshold超過面を結果として選択します。

## Recommended workflow

### Protected UV Workflow

Protection is explicit and persistent. It never infers manual work from UV
changes or Blender pins, and it does not install a background watcher.

- **Finished** protects an island's seam state, UV topology/continuity, and all
  UV coordinates (position, scale, and rotation) from automatic modification.
- **Layout Lock** protects only placement, scale, and rotation during weighted
  layout and packing. It does not prevent seam generation, unwrap, or explicit
  symmetry tools.

Both values are stored on the Mesh as face-domain integer attributes:
`autoseam_finished_group` and `autoseam_layout_lock`. Each island marked in one
action receives a distinct positive Finished group ID. A partial face selection
is expanded to the complete current UV island without changing selection.
Finished and Layout Lock remain independent from the edge-domain Force/Protect
candidate tags. Linked objects therefore see the same protection and the
**Process Shared Mesh Data Once** policy still applies.

Recommended iterative workflow:

1. Auto Seam.
2. Unwrap.
3. Weighted Layout.
4. Manually correct important UV islands.
5. Mark completed islands as **Finished**.
6. Manually position islands that should stay fixed.
7. Apply **Layout Lock**.
8. Continue automatic processing.
9. Use **Pack Selected Into Free Space** for newly added or reworked islands.

Weighted Layout and Shared Weighted Atlas use locked/Finished bounding boxes as
fixed MaxRects obstacles. Only the obstacle portion inside FULL, LEFT_HALF, or
RIGHT_HALF consumes free space. Existing overlapping locked islands are left
untouched. Obstacles receive one margin halo and movable rectangles retain their
existing one margin halo, so the existing two-sided padding is not counted
twice. Optional 90-degree rotation applies only to movable islands.

Pack Selected Into Free Space treats selected editable islands as one movable
pool and every other island as an obstacle. It uses one common fit scale,
performs Collect → Validate → Plan → write-barrier → Commit, and restores the
pre-commit coordinates if committing fails. Symmetry operations transactionally
cancel rather than partially writing when any target belongs to a Finished
island. Mixed protection values inside one current UV island are reported as an
inconsistent state and are never guessed or repaired.

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
- Protection follows Mesh face attributes. If GoZ or another operation replaces
  the entire mesh topology, protection may not survive and must be assigned
  again. v1 intentionally performs no nearest-face, position, or projection
  remapping after arbitrary topology replacement.
