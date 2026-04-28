{-# LANGUAGE BangPatterns #-}
-- Self-contained testbench: what fraction of naively generated trees are BSTs?
-- No external deps — just `runghc bst-naive.hs`.

module Main where

import qualified Data.Map.Strict as M
import           Data.Word        (Word64)
import           Text.Printf      (printf)

------------------------------------------------------------
-- Tiny LCG so we don't need the `random` package
------------------------------------------------------------

type Seed = Word64

step :: Seed -> Seed
step s = s * 6364136223846793005 + 1442695040888963407

-- Uniform Int in [lo, hi]; returns next seed.
range :: Int -> Int -> Seed -> (Int, Seed)
range lo hi s =
  let s' = step s
      n  = hi - lo + 1
      v  = fromIntegral (s' `quot` 65536) `mod` n
  in (lo + v, s')

------------------------------------------------------------
-- Trees and the naive generator
------------------------------------------------------------

data Tree a = Leaf | Node (Tree a) a (Tree a) deriving Show

-- Naive (size-bounded) generator. Mirrors:
--   sized $ \n -> if n == 0 then pure Leaf else
--     frequency [(1, pure Leaf),
--                (3, Node <$> gen (n `div` 2) <*> arbitrary <*> gen (n `div` 2))]
-- The keyspace is [0..99] so collisions are realistic but values aren't tiny.
genTree :: Int -> Seed -> (Tree Int, Seed)
genTree 0 s = (Leaf, s)
genTree n s =
  let (r, s1) = range 0 3 s    -- 1:3 Leaf:Node
  in if r == 0
       then (Leaf, s1)
       else let (x,  s2) = range 0 99 s1
                (l,  s3) = genTree (n `div` 2) s2
                (rt, s4) = genTree (n `div` 2) s3
            in (Node l x rt, s4)

------------------------------------------------------------
-- Predicates
------------------------------------------------------------

isBST :: Ord a => Tree a -> Bool
isBST = go Nothing Nothing
  where
    go _  _  Leaf         = True
    go lo hi (Node l x r) =
         maybe True (x >) lo
      && maybe True (x <) hi
      && go lo (Just x) l
      && go (Just x) hi r

treeSize :: Tree a -> Int
treeSize Leaf         = 0
treeSize (Node l _ r) = 1 + treeSize l + treeSize r

------------------------------------------------------------
-- Driver — bucket samples by *actual* tree size
------------------------------------------------------------

-- (count, bstCount) per actual tree size.
type Buckets = M.Map Int (Int, Int)

bump :: Tree Int -> Buckets -> Buckets
bump t = M.insertWith add (treeSize t) (1, ok)
  where
    ok            = if isBST t then 1 else 0
    add (a,b) (c,d) = let !x = a+c; !y = b+d in (x, y)

run :: Int -> Int -> Seed -> Buckets
run trials sz s0 = go trials s0 M.empty
  where
    go 0 _ !m = m
    go k s !m =
      let (t, s') = genTree sz s
      in go (k-1) s' (bump t m)

pct :: Int -> Int -> Double
pct _ 0 = 0
pct a b = 100 * fromIntegral a / fromIntegral b

main :: IO ()
main = do
  let trials = 200000
      budget = 64               -- generator size parameter (high enough to populate buckets 0..7)
      seed0  = 0xdeadbeefcafebabe
      bs     = run trials budget seed0

      -- aggregate counts at sizes ≥ 8 into one overflow row
      (small, big) = M.partitionWithKey (\k _ -> k <= 7) bs
      overflow     = M.foldl' (\(a,b) (c,d) -> (a+c, b+d)) (0,0) big

  printf "naive generator: budget=%d  trials=%d\n\n" budget trials
  printf "%-6s %-10s %-8s %-10s %-10s\n"
         ("nodes"::String) ("count"::String) ("#BST"::String)
         ("%BST"::String) ("%popl"::String)

  let total = trials
  mapM_ (\n -> do
      let (c, b) = M.findWithDefault (0,0) n bs
      printf "%-6d %-10d %-8d %-10.2f %-10.2f\n"
             n c b (pct b c) (pct c total))
    [0..7 :: Int]

  let (oc, ob) = overflow
  printf "%-6s %-10d %-8d %-10.2f %-10.2f\n"
         ("≥8"::String) oc ob (pct ob oc) (pct oc total)
